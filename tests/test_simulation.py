"""Mechanics and recovery evidence independent of model narration."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from mythfall.simulation import ActionError, Simulation, new_world
from mythfall.simulation.actions import apply_action
from mythfall.simulation.perception import can_see, observe
from mythfall.simulation.state import PLAYER, TICKS_PER_HOUR
from mythfall.simulation.store import WorldStore


def finish(simulation, command, op="wait", chunk_ticks=300):
    result = simulation.command(command, op, chunk_ticks=chunk_ticks)
    count = 0
    while result["reason"] == "yielded":
        count += 1
        result = simulation.command({"kind": "resume", "wait_id": op}, f"{op}.{count}", chunk_ticks=chunk_ticks)
    return result


def gameplay(world):
    value = deepcopy(world)
    for key in ("receipts", "revision", "pending"):
        value.pop(key, None)
    for event in value["events"]:
        event.pop("operation_id", None)
    return value


class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.sim = Simulation(new_world())

    def drop(self, target="item.sword"):
        return self.sim.command({"kind": "drop", "target": target}, "drop")

    def test_an_unnoticed_item_remains_on_the_ground(self):
        for aid, actor in self.sim.world["actors"].items():
            if aid != PLAYER:
                actor["position"] = [56, 37]
                actor["work"] = [56, 37]
        self.drop()
        result = finish(self.sim, {"kind": "wait", "ticks": 50, "until": {"kind": "item_taken", "target": "item.sword"}})
        self.assertEqual(result["reason"], "timeout")
        self.assertEqual(self.sim.world["items"]["item.sword"]["place"], {"ground": [24, 24]})
        self.assertFalse(any(e["kind"] == "notice" for e in self.sim.world["events"]))

    def test_visible_but_unreachable_property_is_not_collected(self):
        world = self.sim.world
        for aid, actor in world["actors"].items():
            if aid != PLAYER:
                actor["interest"] = "none"
        nessa = world["actors"]["char.old_nessa"]
        nessa.update(position=[22, 22], work=[22, 22], interest="safekeep")
        world["map"]["walls"].extend([[23, 24], [25, 24], [24, 23], [24, 25]])
        self.assertTrue(can_see(world, "char.old_nessa", [24, 24]))
        self.drop()
        result = finish(self.sim, {"kind": "wait", "ticks": 50, "until": {"kind": "item_taken", "target": "item.sword"}})
        self.assertEqual(result["reason"], "timeout")
        self.assertEqual(self.sim.world["items"]["item.sword"]["place"], {"ground": [24, 24]})

    def test_save_pending_then_resume_with_different_chunk_size_is_equivalent(self):
        fast = Simulation(deepcopy(self.sim.world))
        finish(fast, {"kind": "wait", "ticks": 1000}, chunk_ticks=300)
        self.sim.command({"kind": "wait", "ticks": 1000}, "wait", chunk_ticks=13)
        resumed = Simulation(json.loads(json.dumps(self.sim.world)))
        n = 0
        while resumed.world["pending"]["status"] == "running":
            n += 1
            resumed.command({"kind": "resume", "wait_id": "wait"}, f"saved.{n}", chunk_ticks=71)
        self.assertEqual(gameplay(fast.world), gameplay(resumed.world))

    def test_observing_and_rendering_do_not_advance_time(self):
        from mythfall.simulation.presentation import packet, scene
        before = deepcopy(self.sim.world)
        for _ in range(3):
            self.sim.observe()
            packet(self.sim.world)
            scene(self.sim.world)
        self.assertEqual(before, self.sim.world)

    def test_tired_npc_finishes_a_rest_cycle_instead_of_thrashing_between_bed_and_work(self):
        nessa = self.sim.world["actors"]["char.old_nessa"]
        nessa.update(position=nessa["home"][:], fatigue=9100)
        finish(self.sim, {"kind": "wait", "ticks": 500})
        self.assertEqual(nessa["home"], self.sim.world["actors"]["char.old_nessa"]["position"])
        self.assertEqual(self.sim.world["actors"]["char.old_nessa"]["activity"], "sleeping")
        self.assertFalse(any(e["kind"] == "move" and e["actor"] == "char.old_nessa" for e in self.sim.world["events"]))

    def test_an_encounter_interrupts_an_active_wait_at_the_next_decision_boundary(self):
        self.sim.world["actors"][PLAYER]["position"] = [10, 24]
        self.sim.command({"kind": "npc_plan", "actor": "char.brakka", "actions": [{"kind": "attack", "target": PLAYER}],
                          "reason": "Recorded hostile decision."}, "decision")
        result = self.sim.command({"kind": "wait", "ticks": 100}, "danger")
        self.assertEqual(result["reason"], "combat_decision")
        self.assertEqual(result["elapsed_ticks"], 1)
        self.assertEqual(self.sim.world["combat"]["awaiting"], self.sim.world["combat"]["participants"][0]["id"])
        self.assertEqual(self.sim.world["actors"]["char.tommen_ash"]["hunger"], 2001)

    def test_sword_is_noticed_approached_and_taken_by_an_npc(self):
        self.drop()
        dropped = self.sim.world["items"]["item.sword"]["place"]
        self.assertEqual(dropped, {"ground": [24, 24]})
        result = finish(self.sim, {"kind": "wait", "ticks": 300, "until": {"kind": "item_taken", "target": "item.sword"}})
        self.assertEqual(result["reason"], "condition_reached")
        carrier = self.sim.world["items"]["item.sword"]["place"]["carrier"]
        self.assertNotEqual(carrier, PLAYER)
        kinds = [e["kind"] for e in self.sim.world["events"] if e["actor"] == carrier]
        self.assertIn("notice", kinds)
        self.assertIn("move", kinds)
        self.assertIn("take", kinds)
        self.assertEqual(self.sim.world["items"]["item.sword"]["owner"], PLAYER)

    def test_intervening_before_pickup_invalidates_the_npc_plan(self):
        self.drop()
        self.sim.command({"kind": "take", "target": "item.sword"}, "intervene")
        finish(self.sim, {"kind": "wait", "ticks": 100})
        self.assertEqual(self.sim.world["items"]["item.sword"]["place"], {"carrier": PLAYER})
        self.assertTrue(any(e["kind"] == "plan_blocked" for e in self.sim.world["events"]))

    def test_nobody_interested_means_timeout(self):
        for actor in self.sim.world["actors"].values():
            actor["interest"] = "none"
        self.drop()
        result = finish(self.sim, {"kind": "wait", "ticks": 30, "until": {"kind": "item_taken", "target": "item.sword"}})
        self.assertEqual(result["reason"], "timeout")
        self.assertIn("ground", self.sim.world["items"]["item.sword"]["place"])

    def test_a_different_item_uses_the_same_behavior(self):
        self.drop("item.lantern")
        result = finish(self.sim, {"kind": "wait", "ticks": 60, "until": {"kind": "item_taken", "target": "item.lantern"}})
        self.assertEqual(result["reason"], "condition_reached")
        self.assertNotEqual(self.sim.world["items"]["item.lantern"]["place"].get("carrier"), PLAYER)

    def test_competing_takers_produce_one_transfer(self):
        self.sim.world["actors"]["char.brakka"]["position"] = [24, 25]
        self.drop()
        finish(self.sim, {"kind": "wait", "ticks": 80})
        pickups = [e for e in self.sim.world["events"] if e["kind"] == "take" and e["targets"] == ["item.sword"]]
        self.assertEqual(len(pickups), 1)
        self.assertEqual(self.sim.world["items"]["item.sword"]["place"], {"carrier": pickups[0]["actor"]})

    def test_retry_does_not_repeat_a_mutation_and_conflicting_retry_fails(self):
        first = self.drop()
        state = deepcopy(self.sim.world)
        self.assertEqual(first, self.sim.command({"kind": "drop", "target": "item.sword"}, "drop", expected_revision=0))
        self.assertEqual(state, self.sim.world)
        with self.assertRaises(ActionError):
            self.sim.command({"kind": "drop", "target": "item.lantern"}, "drop")
        self.assertEqual(state, self.sim.world)

    def test_failed_action_and_stale_revision_leave_state_unchanged(self):
        original = deepcopy(self.sim.world)
        with self.assertRaises(ActionError):
            self.sim.command({"kind": "move", "position": [63, 45]}, "teleport")
        with self.assertRaises(ActionError):
            self.sim.command({"kind": "drop", "target": "item.sword"}, "stale", expected_revision=99)
        self.assertEqual(self.sim.world, original)

    def test_single_steps_match_acceleration_with_the_same_decisions(self):
        a, b = Simulation(new_world()), Simulation(new_world())
        a.command({"kind": "drop", "target": "item.sword"}, "drop")
        b.command({"kind": "drop", "target": "item.sword"}, "drop")
        finish(a, {"kind": "wait", "ticks": 120}, "batch")
        for n in range(120):
            b.command({"kind": "wait", "ticks": 1}, f"step.{n}")
        self.assertEqual(gameplay(a.world), gameplay(b.world))

    def test_cancel_and_reopen_a_pending_wait(self):
        result = self.sim.command({"kind": "wait", "ticks": 100}, "long", chunk_ticks=5)
        self.assertEqual(result["reason"], "yielded")
        restored = Simulation(json.loads(json.dumps(self.sim.world)))
        tick = restored.world["tick"]
        result = restored.command({"kind": "cancel", "wait_id": "long"}, "cancel")
        self.assertEqual(result["reason"], "cancelled")
        self.assertEqual(restored.world["tick"], tick)
        with self.assertRaises(ActionError):
            restored.command({"kind": "resume", "wait_id": "long"}, "late-resume")

    def test_world_time_wait_and_immediate_condition(self):
        result = self.sim.command({"kind": "wait", "ticks": 50, "until": {"kind": "actor_arrived", "target": "char.old_nessa"}}, "arrived")
        self.assertEqual(result["reason"], "condition_reached")
        self.assertEqual(result["elapsed_ticks"], 0)
        finish(self.sim, {"kind": "wait", "until_hour": 9}, "hour")
        self.assertEqual(self.sim.world["tick"], 9 * TICKS_PER_HOUR)

    def test_wait_cannot_reveal_an_unseen_actor_or_hidden_inventory(self):
        self.assertFalse(can_see(self.sim.world, PLAYER, self.sim.world["actors"]["char.ellis_crow"]["position"]))
        with self.assertRaises(ActionError):
            self.sim.command({"kind": "wait", "until": {"kind": "actor_arrived", "target": "char.ellis_crow"}}, "secret")
        visible = observe(self.sim.world, PLAYER)
        self.assertNotIn("char.ellis_crow", {a["id"] for a in visible["actors"]})
        self.assertNotIn("item.charm", {i["id"] for i in visible["items"]})

    def test_walls_and_closed_doors_block_travel(self):
        self.sim.world["map"]["doors"]["door.inn"]["open"] = False
        with self.assertRaises(ActionError):
            self.sim.command({"kind": "travel", "target": "inn"}, "closed")
        self.sim.world["map"]["doors"]["door.inn"]["open"] = True
        result = finish(self.sim, {"kind": "travel", "target": "inn"}, "open")
        self.assertEqual(result["reason"], "arrived")
        self.assertEqual(self.sim.world["actors"][PLAYER]["position"], [42, 23])

    def test_sleeping_observer_does_not_receive_hidden_pickup(self):
        self.drop()
        result = finish(self.sim, {"kind": "wait", "ticks": 30, "activity": "rest", "until": {"kind": "item_taken", "target": "item.sword"}})
        self.assertEqual(result["reason"], "timeout")
        self.assertIn("carrier", self.sim.world["items"]["item.sword"]["place"])
        self.assertFalse(any(e["kind"] == "take" for e in result["events"]))

    def test_combat_uses_seeded_rules_and_stops_duration_waits(self):
        self.sim.world["actors"]["char.brakka"]["position"] = [24, 25]
        self.sim.command({"kind": "equip", "target": "item.sword"}, "equip")
        before = self.sim.world["tick"]
        result = self.sim.command({"kind": "attack", "target": "char.brakka"}, "attack")
        self.assertEqual(self.sim.world["tick"], before)
        self.assertEqual(result["reason"], "combat_decision")
        self.assertLessEqual(len([e for e in result["events"] if e["kind"] == "attack"]), 1)
        self.assertEqual({entry["id"] for entry in self.sim.world["combat"]["participants"]}, {PLAYER, "char.brakka"})
        with self.assertRaises(ActionError):
            self.sim.command({"kind": "wait", "ticks": 100}, "ignore-combat")

    def test_npc_knowledge_does_not_update_when_an_unseen_item_moves(self):
        self.sim.world["actors"][PLAYER]["position"] = [56, 37]
        apply_action(self.sim.world, PLAYER, {"kind": "drop", "target": "item.sword"})
        self.assertNotIn("item.sword", self.sim.world["actors"]["char.old_nessa"]["known"])

    def test_save_resume_and_duplicate_request_preserve_exact_state(self):
        with tempfile.TemporaryDirectory() as directory:
            store = WorldStore(Path(directory))
            store.ensure()
            first, world = store.execute({"kind": "drop", "target": "item.sword"}, "drop")
            self.assertEqual(world, WorldStore(directory).read())
            repeated, reloaded = WorldStore(directory).execute({"kind": "drop", "target": "item.sword"}, "drop")
            self.assertEqual(first, repeated)
            self.assertEqual(world, reloaded)
            resumed = Simulation(reloaded)
            uninterrupted = Simulation(world)
            command = {"kind": "wait", "ticks": 100}
            finish(resumed, command)
            finish(uninterrupted, command)
            self.assertEqual(resumed.world, uninterrupted.world)


if __name__ == "__main__":
    unittest.main()
