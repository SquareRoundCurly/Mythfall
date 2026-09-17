"""Composition and information boundaries, independent of LLM narration."""

from copy import deepcopy
import json
import unittest

from mythfall.simulation import ActionError, Simulation, new_world
from mythfall.simulation.actions import apply_action
from mythfall.simulation.effects import apply_effect, expire_effects
from mythfall.simulation.migration import upgrade_world
from mythfall.simulation.minds import reference, resolve_reference
from mythfall.simulation.perception import observe
from mythfall.simulation.presentation import packet
from mythfall.simulation.state import PLAYER
from mythfall.world_agent import knowledge


class MindsEffectsTests(unittest.TestCase):
    def setUp(self):
        self.world = new_world()
        self.listener = "char.old_nessa"
        self.world["actors"][self.listener]["position"] = [22, 24]

    def test_invisibility_filters_actor_and_equipment_but_not_received_speech(self):
        self.world["actors"][PLAYER]["equipped"] = "item.sword"
        apply_effect(self.world, PLAYER, PLAYER, {"kind": "condition", "condition": "invisible", "duration": 10})
        view = observe(self.world, self.listener)
        self.assertNotIn(PLAYER, {a["id"] for a in view["actors"]})
        self.assertNotIn("item.sword", {i["id"] for i in view["items"]})
        before = self.world["rng"]
        with self.assertRaises(ActionError):
            apply_action(self.world, self.listener, {"kind": "attack", "target": PLAYER})
        self.assertEqual(self.world["rng"], before)
        apply_action(self.world, PLAYER, {"kind": "speak", "text": "Hello from concealment."})
        memory = self.world["actors"][self.listener]["memories"][-1]
        self.assertEqual(memory["text"], "Hello from concealment.")
        self.assertEqual(memory["actor"], "unknown")
        self.assertEqual(memory["speaker"], "Someone")

    def test_sound_reaches_around_corner_without_revealing_its_source(self):
        self.world["map"]["walls"].append([23, 24])
        apply_effect(self.world, PLAYER, PLAYER, {"kind": "sound", "volume": 4})
        event = self.world["actors"][self.listener]["memories"][-1]
        self.assertEqual(event["kind"], "sound")
        self.assertEqual(event["actor"], "unknown")
        self.assertEqual(event["position"], [24, 24])
        self.assertNotIn(PLAYER, json.dumps(event))
        self.assertEqual(self.world["actors"][self.listener]["attention"][-1]["position"], [24, 24])

    def test_whisper_and_language_apply_to_every_listener_without_an_agent_call(self):
        self.world["actors"][self.listener]["position"] = [23, 24]
        bystander = self.world["actors"]["char.tommen_ash"]
        bystander["position"] = [24, 25]
        bystander["languages"] = ["dwarvish"]
        distant = self.world["actors"]["char.brakka"]
        distant["position"] = [26, 24]
        apply_action(self.world, PLAYER, {"kind": "speak", "channel": "whisper", "target": self.listener, "text": "PRIVATE_WORDS"})
        self.assertEqual(self.world["actors"][self.listener]["memories"][-1]["text"], "PRIVATE_WORDS")
        self.assertEqual(bystander["memories"][-1]["text"], "Speech in an unfamiliar language.")
        self.assertNotIn("PRIVATE_WORDS", json.dumps(distant["memories"]))

    def test_memory_alteration_removes_original_from_future_context_but_preserves_ledger(self):
        apply_action(self.world, PLAYER, {"kind": "speak", "text": "ORIGINAL_SECRET"})
        actor = self.world["actors"][self.listener]
        event_id = actor["memories"][-1]["sequence"]
        actor["plan"] = {"actions": [{"kind": "speak", "text": "ORIGINAL_SECRET"}]}
        actor["beliefs"] = [{"text": "ORIGINAL_SECRET", "source_sequence": event_id}]
        actor["thoughts"] = [{"text": "ORIGINAL_SECRET", "source_sequence": event_id, "amount": -3, "ends_at": 10000}]
        apply_effect(self.world, PLAYER, self.listener, {"kind": "memory", "sequences": [event_id], "text": "We discussed the weather."})
        restored = upgrade_world(json.loads(json.dumps(self.world)))
        view = knowledge(restored, self.listener)
        self.assertNotIn("ORIGINAL_SECRET", json.dumps(view))
        self.assertIn("We discussed the weather.", json.dumps(view))
        self.assertIn("ORIGINAL_SECRET", json.dumps(restored["events"]))
        self.assertIsNone(view["self"]["plan"])
        self.assertNotIn("suppressed_events", view["self"])

    def test_perceived_identity_uses_enemy_relationship_and_resolvable_opaque_handle(self):
        actor = self.world["actors"][self.listener]
        actor["relationships"] = {PLAYER: 8, "char.brakka": -9}
        apply_effect(self.world, PLAYER, self.listener, {"kind": "identity", "subject": PLAYER,
            "identity": "char.brakka", "name": "Brakka", "duration": 3})
        view = observe(self.world, self.listener)
        handle = reference(self.world, self.listener, PLAYER)
        self.assertTrue(handle.startswith("seen."))
        self.assertEqual(resolve_reference(self.world, self.listener, handle), PLAYER)
        apparent = next(a for a in view["actors"] if a["id"] == handle)
        self.assertEqual(apparent["name"], "Brakka")
        self.assertEqual(view["self"]["relationships"][handle], -9)
        self.assertEqual(actor["relationships"][PLAYER], 8)
        self.assertNotIn(PLAYER, json.dumps(view))
        self.world["tick"] += 3
        expire_effects(self.world)
        self.assertEqual(reference(self.world, self.listener, PLAYER), PLAYER)
        self.assertEqual(actor["relationships"][PLAYER], 8)

    def test_disguise_changes_browser_projection_without_hiding_the_physical_actor(self):
        apply_effect(self.world, self.listener, self.listener, {"kind": "disguise", "identity": "visitor", "name": "Masked visitor", "duration": 5})
        view = packet(self.world)
        self.assertIn("Masked visitor", [a["name"] for a in view["world"]["actors"]])
        visible_names = [e["name"] for e in view["render"] if e.get("drawable", {}).get("visible")]
        self.assertTrue(any("Masked visitor" in name for name in visible_names))
        self.assertFalse(any("Old Nessa" in name for name in visible_names))

    def test_timed_effects_and_thoughts_survive_reload_and_expire_only_with_game_time(self):
        apply_effect(self.world, PLAYER, self.listener, {"kind": "thought", "text": "A reassuring memory", "amount": 5, "duration": 3})
        apply_effect(self.world, PLAYER, self.listener, {"kind": "condition", "condition": "invisible", "duration": 3})
        before = deepcopy(self.world)
        for _ in range(3):
            packet(self.world)
            knowledge(self.world, self.listener)
        self.assertEqual(self.world, before)
        sim = Simulation(json.loads(json.dumps(self.world)))
        self.assertEqual(knowledge(sim.world, self.listener)["self"]["mood"], 5)
        sim.command({"kind": "wait", "ticks": 3}, "three-ticks")
        self.assertEqual(knowledge(sim.world, self.listener)["self"]["mood"], 0)
        self.assertEqual(sim.world["effects"], {})

    def test_migration_is_idempotent_and_keeps_physical_state_and_saved_receipts(self):
        self.world["version"] = 1
        self.world["receipts"]["old-operation"] = {"intent": "old", "result": {"tick": 4799}}
        original = deepcopy(self.world)
        upgraded = upgrade_world(self.world)
        self.assertEqual(self.world, original)
        self.assertEqual(upgraded["items"], original["items"])
        self.assertEqual(upgraded["receipts"], original["receipts"])
        self.assertEqual(upgrade_world(upgraded), upgraded)


if __name__ == "__main__":
    unittest.main()
