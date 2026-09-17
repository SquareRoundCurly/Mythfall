from copy import deepcopy
import json
import unittest

from mythfall.simulation import ActionError, Simulation, new_world
from mythfall.simulation.authoring import validate_definition
from mythfall.simulation.catalog import starting_catalog
from mythfall.simulation.characters import choose_class, instantiate, prepared_abilities, armor_class
from mythfall.simulation.checks import check
from mythfall.simulation.combat import start, begin_turn
from mythfall.simulation.effects import apply_effect
from mythfall.simulation.minds import has_condition
from mythfall.simulation.state import PLAYER, emit
from mythfall.simulation.presentation import packet
from test_simulation import finish, gameplay


class RpgRulesTests(unittest.TestCase):
    def setUp(self):
        self.sim = Simulation(new_world())
        for actor in self.sim.world["actors"].values():
            actor["interest"] = "none"
            actor["ready_at"] = 100000

    def build(self, name, **options):
        return self.sim.command({"kind": "choose_class", "class": name, **options}, "build." + str(self.sim.world["revision"]))

    def player_turn(self, enemies=("char.brakka",)):
        for index, aid in enumerate(enemies):
            self.sim.world["actors"][aid].update(position=[24, 25 + index], hp=100, max_hp=100)
        start(self.sim.world, PLAYER, list(enemies))
        combat = self.sim.world["combat"]
        combat["turn"] = next(n for n, entry in enumerate(combat["participants"]) if entry["id"] == PLAYER)
        begin_turn(self.sim.world)

    def test_every_catalog_definition_has_supported_executable_semantics(self):
        for key, spec in starting_catalog().items():
            with self.subTest(key=key):
                self.assertEqual(validate_definition(spec), spec)

    def test_light_survives_an_hour_and_save_reload_then_expires_at_two_hours(self):
        from mythfall.simulation.perception import can_see
        self.build("cleric")
        self.sim.command({"kind": "unequip", "slot": "weapon"}, "free-hand")
        dark = [26, 24]
        self.sim.world["map"]["dark_tiles"] = [dark]
        for item in list(self.sim.world["items"].values()) + list(self.sim.world["fixtures"].values()):
            item["lit"] = False
            item.pop("light", None)
        self.assertFalse(can_see(self.sim.world, PLAYER, dark))
        started = self.sim.world["tick"]
        self.sim.command({"kind": "ability", "ability": "ability.light@1", "target": "item.sword"}, "light")
        ends = self.sim.world["items"]["item.sword"]["light"]["ends_at"]
        self.assertEqual(ends, started + 1200)
        finish(self.sim, {"kind": "wait", "ticks": 600}, "first-hour")
        self.sim = Simulation(json.loads(json.dumps(self.sim.world)))
        self.assertTrue(can_see(self.sim.world, PLAYER, dark))
        finish(self.sim, {"kind": "wait", "ticks": ends - self.sim.world["tick"]}, "second-hour")
        self.assertFalse(can_see(self.sim.world, PLAYER, dark))

    def test_level_features_resources_and_srd_subclass_survive_reload(self):
        self.build("fighter", style="dueling")
        player = self.sim.world["actors"][PLAYER]
        player["hp"] = 2
        self.sim.command({"kind": "ability", "ability": "ability.second_wind@1"}, "wind")
        self.assertGreater(self.sim.world["actors"][PLAYER]["hp"], 2)
        self.assertEqual(self.sim.world["actors"][PLAYER]["rpg"]["resources"]["second_wind"]["current"], 0)
        self.sim.world["actors"][PLAYER]["rpg"]["xp"] = 900
        self.build("fighter")
        self.build("fighter")
        self.sim = Simulation(json.loads(json.dumps(self.sim.world)))
        player = self.sim.world["actors"][PLAYER]
        self.assertEqual(player["rpg"]["subclasses"]["fighter"], "champion")
        self.assertIn("improved_critical", player["rpg"]["features"])
        self.assertIn("ability.action_surge@1", prepared_abilities(self.sim.world, PLAYER))
        self.assertEqual(player["rpg"]["resources"]["hit_dice_fighter"]["max"], 3)

    def test_multiclass_prerequisites_and_slots_dont_grant_higher_spells(self):
        self.build("wizard")
        self.sim.world["actors"][PLAYER]["rpg"]["xp"] = 900
        before = deepcopy(self.sim.world)
        with self.assertRaisesRegex(ActionError, "13"):
            self.build("cleric")
        self.assertEqual(before, self.sim.world)
        self.sim.world["actors"][PLAYER]["stats"].update(int=14, wis=14)
        self.build("wizard")
        self.build("cleric")
        player = self.sim.world["actors"][PLAYER]
        self.assertEqual(player["rpg"]["resources"]["slot_2"]["max"], 2)
        self.assertIn("sculpt_spells", player["rpg"]["features"])
        self.assertNotIn("ability.invisibility@1", prepared_abilities(self.sim.world, PLAYER))

    def test_skills_expertise_saves_and_guidance_are_shared_checks(self):
        self.build("rogue", skills=["stealth", "perception", "investigation", "athletics"], expertise=["stealth", "perception"])
        base = deepcopy(self.sim.world)
        expert = check(self.sim.world, PLAYER, skill="stealth")
        novice = check(base, PLAYER, stat="dex")
        self.assertEqual(expert["total"] - novice["total"], 4)
        saved = check(base, PLAYER, stat="dex", saving=True)
        self.assertEqual(saved["training"], 2)
        apply_effect(base, PLAYER, PLAYER, {"kind": "check_bonus", "dice": "1d4", "duration": 10, "once": True})
        first = check(base, PLAYER, skill="arcana")
        second = check(base, PLAYER, skill="arcana")
        self.assertEqual(len(first["bonuses"]), 1)
        self.assertFalse(second["bonuses"])

    def test_party_round_advances_once_and_npc_routines_cannot_double_act(self):
        self.build("fighter")
        self.sim.world["party"]["members"].append("char.old_nessa")
        self.sim.world["actors"]["char.old_nessa"]["position"] = [23, 24]
        self.player_turn(("char.brakka", "char.tommen_ash"))
        combat = self.sim.world["combat"]
        # Start at the first initiative entry and pass a complete round.
        combat["turn"] = 0
        begin_turn(self.sim.world)
        before_tick, sequence = self.sim.world["tick"], self.sim.world["sequence"]
        for n in range(4):
            aid = self.sim.world["combat"]["awaiting"]
            command = {"kind": "end_turn"} if aid == PLAYER else {"kind": "npc_turn", "actor": aid, "actions": [{"kind": "end_turn"}], "mind_revision": self.sim.world["actors"][aid]["mind_revision"]}
            self.sim.command(command, f"pass.{n}")
        self.assertEqual(self.sim.world["tick"], before_tick + 1)
        self.assertEqual(self.sim.world["combat"]["round"], 2)
        self.assertFalse(any(event["kind"] in {"move", "attack"} for event in self.sim.world["events"] if event["sequence"] > sequence))

    def test_action_surge_allows_only_one_extra_action_and_bonus_has_separate_cost(self):
        self.build("fighter")
        self.sim.world["actors"][PLAYER]["rpg"]["xp"] = 300
        self.build("fighter")
        self.player_turn()
        self.sim.command({"kind": "attack", "target": "char.brakka"}, "attack1")
        before = deepcopy(self.sim.world)
        with self.assertRaisesRegex(ActionError, "No action"):
            self.sim.command({"kind": "attack", "target": "char.brakka"}, "attack2")
        self.assertEqual(before, self.sim.world)
        self.sim.command({"kind": "ability", "ability": "ability.action_surge@1"}, "surge")
        self.sim.command({"kind": "attack", "target": "char.brakka"}, "attack3")
        self.sim.command({"kind": "ability", "ability": "ability.second_wind@1"}, "bonus")
        budget = self.sim.world["combat"]["economy"][PLAYER]
        self.assertEqual((budget["action"], budget["bonus"]), (0, 0))

    def test_healing_uses_slot_life_bonus_and_does_not_recast_on_retry(self):
        self.build("cleric")
        self.sim.world["actors"][PLAYER]["equipped"] = None
        self.sim.world["actors"][PLAYER]["hp"] = 1
        intent = {"kind": "ability", "ability": "ability.cure_wounds@1", "target": PLAYER}
        result = self.sim.command(intent, "heal")
        after = deepcopy(self.sim.world)
        self.assertGreaterEqual(after["actors"][PLAYER]["hp"], 6)
        self.assertEqual(after["actors"][PLAYER]["rpg"]["resources"]["slot_1"]["current"], 1)
        self.assertEqual(result, self.sim.command(intent, "heal"))
        self.assertEqual(after, self.sim.world)

    def test_short_rest_has_real_duration_and_cancelled_rest_gives_no_resources(self):
        self.build("fighter")
        self.sim.command({"kind": "ability", "ability": "ability.second_wind@1"}, "wind")
        result = self.sim.command({"kind": "short_rest"}, "rest", chunk_ticks=5)
        self.assertEqual(result["reason"], "yielded")
        self.sim.command({"kind": "cancel", "wait_id": "rest"}, "cancel")
        self.assertEqual(self.sim.world["actors"][PLAYER]["rpg"]["resources"]["second_wind"]["current"], 0)
        tick = self.sim.world["tick"]
        finish(self.sim, {"kind": "short_rest"}, "rest-again")
        self.assertEqual(self.sim.world["tick"], tick + 600)
        self.assertEqual(self.sim.world["actors"][PLAYER]["rpg"]["resources"]["second_wind"]["current"], 1)

    def test_party_panels_do_not_contain_private_npc_memory(self):
        self.build("fighter")
        self.sim.world["party"]["members"].append("char.old_nessa")
        self.sim.world["actors"]["char.old_nessa"]["lore"] = "PRIVATE_LEDGER_SECRET"
        self.sim.world["actors"]["char.old_nessa"]["memories"].append({"sequence": 1, "text": "PRIVATE_LEDGER_SECRET"})
        projected = packet(self.sim.world)
        self.assertNotIn("PRIVATE_LEDGER_SECRET", json.dumps(projected))
        self.assertEqual(projected["world"]["characters"][PLAYER]["armor_class"], armor_class(self.sim.world, PLAYER))

    def test_content_definition_is_not_a_grant_and_revision_keeps_existing_meaning(self):
        spec = {"type": "ability", "name": "Quiet Rebuke", "description": "A remembered warning.", "level": 0, "classes": [],
                "spell": False, "components": [], "economy": "action", "range": 4, "max_targets": 1, "target": "creature",
                "resolution": "automatic", "effects": [{"kind": "thought", "text": "A troubling warning", "amount": -3, "duration": 10}]}
        self.sim.command({"kind": "dm_tools", "operations": [{"kind": "define", "slug": "quiet_rebuke", "definition": spec, "reason": "Record a taught technique as content."}]}, "define")
        key = "ability.quiet_rebuke@1"
        self.assertNotIn(key, prepared_abilities(self.sim.world, PLAYER))
        before = deepcopy(self.sim.world)
        with self.assertRaises(ActionError):
            self.sim.command({"kind": "ability", "ability": key, "target": PLAYER}, "unearned")
        self.assertEqual(before, self.sim.world)
        cause = emit(self.sim.world, "training", PLAYER, text="An hour of supervised mental discipline.")["sequence"]
        self.sim.command({"kind": "dm_tools", "operations": [{"kind": "grant", "actor": PLAYER, "definition": key, "cause": cause, "reason": "Completed supervised training."}]}, "grant")
        self.sim.command({"kind": "ability", "ability": key, "target": PLAYER}, "use")
        self.assertEqual(self.sim.world["actors"][PLAYER]["thoughts"][-1]["amount"], -3)
        spec["effects"][0]["amount"] = -5
        self.sim.command({"kind": "dm_tools", "operations": [{"kind": "define", "slug": "quiet_rebuke", "definition": spec, "reason": "A revised technique for future teaching."}]}, "revise")
        restored = Simulation(json.loads(json.dumps(self.sim.world)))
        self.assertEqual(restored.world["definitions"][key]["effects"][0]["amount"], -3)
        self.assertEqual(restored.world["definitions"]["ability.quiet_rebuke@2"]["effects"][0]["amount"], -5)


if __name__ == "__main__":
    unittest.main()
