"""Shared effects compose across clocks, perception, motives, and movement."""

from copy import deepcopy
import json
import unittest

from mythfall.simulation import Simulation, new_world
from mythfall.simulation.actions import apply_action
from mythfall.simulation.effects import apply_effect
from mythfall.simulation.perception import observe
from mythfall.simulation.routines import choose_action
from mythfall.simulation.schedules import drain, install_schedule
from mythfall.simulation.state import PLAYER


def comparable(world):
    value = deepcopy(world)
    for key in ("receipts", "revision", "pending"):
        value.pop(key, None)
    for event in value["events"]:
        event.pop("operation_id", None)
    return value


class ScheduledConsequencesTests(unittest.TestCase):
    def setUp(self):
        self.world = new_world()
        for actor in self.world["actors"].values():
            actor["interest"] = "none"

    def test_changed_need_routes_to_an_observed_generic_supply_and_consumes_food(self):
        aid = "char.old_nessa"
        actor = self.world["actors"][aid]
        actor.update(position=[22, 24], work=[22, 24])
        for item in self.world["items"].values():
            if item["kind"] == "food" and item["place"].get("carrier") == aid:
                item["place"] = {"consumed": True}
        self.world["fixtures"]["cache.a"] = {"id": "cache.a", "name": "Public supply", "position": [20, 24], "open": True, "offers": ["food"]}
        self.world["items"]["ration.a"] = {"id": "ration.a", "name": "Trail ration", "kind": "food", "place": {"container": "cache.a"},
                                             "owner": aid, "weight": 1, "damage": 0, "condition": 100}
        apply_effect(self.world, PLAYER, aid, {"kind": "need", "need": "hunger", "amount": 5000})
        sim = Simulation(self.world)
        sim.command({"kind": "wait", "ticks": 5}, "watch")
        self.assertEqual(sim.world["items"]["ration.a"]["place"], {"consumed": True})
        self.assertLess(sim.world["actors"][aid]["hunger"], 3000)
        self.assertTrue(any(e["kind"] == "move" and e["actor"] == aid for e in sim.world["events"]))

    def test_hidden_stock_does_not_give_a_hungry_actor_a_destination(self):
        aid = "char.old_nessa"
        actor = self.world["actors"][aid]
        actor.update(hunger=8000, position=[24, 24], work=[24, 24])
        for item in self.world["items"].values():
            if item["place"].get("carrier") == aid and item["kind"] == "food":
                item["place"] = {"ground": [56, 37]}
        self.assertEqual(choose_action(self.world, aid), {"kind": "work"})
        self.assertNotIn("chest.inn", actor["known"])

    def test_sound_investigation_enters_a_zone_and_receives_a_shared_condition(self):
        aid = "char.old_nessa"
        self.world["actors"][aid].update(position=[22, 24], work=[22, 24])
        install_schedule(self.world, {"name": "Binding threshold", "source": PLAYER,
            "trigger": {"kind": "enter", "position": [23, 24], "actor": aid}, "remaining": 1,
            "effects": [{"kind": "condition", "condition": "blinded", "duration": 4, "target": "$actor"}]})
        sound = apply_effect(self.world, PLAYER, PLAYER, {"kind": "sound", "volume": 5, "position": [24, 24]})
        sim = Simulation(self.world)
        sim.command({"kind": "wait", "ticks": 1}, "listen")
        self.assertEqual(sim.world["actors"][aid]["position"], [23, 24])
        self.assertIn("blinded", observe(sim.world, aid)["self"]["conditions"])
        movement = next(e for e in sim.world["events"] if e["kind"] == "move" and e["actor"] == aid)
        effect = next(e for e in sim.world["events"] if e["kind"] == "effect" and e.get("cause") == movement["sequence"])
        self.assertGreater(effect["sequence"], sound["sequence"])
        self.assertEqual(sim.world["consequences"], [])

    def test_duty_can_prevent_investigating_a_distraction(self):
        aid = "char.old_nessa"
        self.world["actors"][aid].update(position=[22, 24], work=[22, 24], duty=80)
        apply_effect(self.world, PLAYER, PLAYER, {"kind": "sound", "volume": 5})
        sim = Simulation(self.world)
        sim.command({"kind": "wait", "ticks": 5}, "guard")
        self.assertEqual(sim.world["actors"][aid]["position"], [22, 24])

    def test_timed_job_fast_forward_and_reload_match_single_steps(self):
        install_schedule(self.world, {"name": "Restful chime", "source": PLAYER,
            "trigger": {"kind": "interval", "every": 3}, "remaining": 3,
            "effects": [{"kind": "need", "need": "fatigue", "amount": -20, "target": "char.old_nessa"}]})
        fast, slow = Simulation(self.world), Simulation(self.world)
        fast.command({"kind": "wait", "ticks": 10}, "fast")
        for n in range(10):
            slow = Simulation(json.loads(json.dumps(slow.world)))
            slow.command({"kind": "wait", "ticks": 1}, f"slow.{n}")
        self.assertEqual(comparable(fast.world), comparable(slow.world))
        self.assertTrue(all(s["remaining"] == 0 for s in fast.world["schedules"].values()))

    def test_bounded_reactions_preserve_work_and_replay_without_duplicate_effects(self):
        for amount in (10, 20, 30):
            install_schedule(self.world, {"source": PLAYER, "trigger": {"kind": "event", "event": "speech"}, "remaining": 1,
                "effects": [{"kind": "need", "need": "hunger", "amount": amount, "target": "char.old_nessa"}]})
        apply_action(self.world, PLAYER, {"kind": "speak", "text": "Start work."})
        before = self.world["actors"]["char.old_nessa"]["hunger"]
        self.assertEqual(drain(self.world, limit=1), 2)
        restored = json.loads(json.dumps(self.world))
        self.assertEqual(drain(restored), 0)
        self.assertEqual(restored["actors"]["char.old_nessa"]["hunger"], before + 60)
        snapshot = deepcopy(restored)
        drain(restored)
        self.assertEqual(restored, snapshot)

    def test_failed_reaction_rolls_back_all_its_effects_and_retains_failure(self):
        sid = install_schedule(self.world, {"source": PLAYER, "trigger": {"kind": "event", "event": "speech"},
            "effects": [{"kind": "need", "need": "hunger", "amount": 100, "target": "char.old_nessa"},
                        {"kind": "heal", "amount": 1, "target": "missing"}]})
        before = self.world["actors"]["char.old_nessa"]["hunger"]
        apply_action(self.world, PLAYER, {"kind": "speak", "text": "Start work."})
        drain(self.world)
        self.assertEqual(self.world["actors"]["char.old_nessa"]["hunger"], before)
        self.assertEqual(len(self.world["schedules"][sid]["failures"]), 1)


if __name__ == "__main__":
    unittest.main()
