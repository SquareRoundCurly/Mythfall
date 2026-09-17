from copy import deepcopy
import json
import unittest

from mythfall.simulation import ActionError, Simulation, new_world
from mythfall.simulation.characters import choose_class, instantiate
from mythfall.simulation.combat import start, begin_turn
from mythfall.simulation.effects import apply_effect
from mythfall.simulation.minds import can_identify, has_condition
from mythfall.simulation.perception import observe
from mythfall.simulation.state import PLAYER, emit
from mythfall.world_agent import knowledge


class RpgBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.sim = Simulation(new_world())
        for body in self.sim.world["actors"].values():
            body["ready_at"] = 999999
            body["interest"] = "none"

    def build(self, aid, name, **options):
        choose_class(self.sim.world, aid, {"class": name, **options})

    def combat(self, source, targets):
        start(self.sim.world, source, targets)
        combat = self.sim.world["combat"]
        combat["turn"] = next(n for n, entry in enumerate(combat["participants"]) if entry["id"] == source)
        begin_turn(self.sim.world)

    def npc_reaction(self, aid, ability=None, op="reaction"):
        return self.sim.command({"kind": "npc_reaction", "actor": aid, "ability": ability,
                                 "mind_revision": self.sim.world["actors"][aid]["mind_revision"]}, op)

    def test_unconscious_life_state_fails_physical_saves_and_close_spell_criticals_count_twice(self):
        from mythfall.simulation.checks import check
        from mythfall.simulation.combat import attack_roll, finish_spell
        world = self.sim.world
        aid = 'char.old_nessa'
        world['party']['members'].append(aid)
        world['actors'][aid].update(position=[24, 25], hp=0, life='unconscious')
        save = check(world, aid, stat='dex', saving=True, difficulty=0)
        self.assertTrue(save['automatic_failure'])
        self.assertFalse(save['success'])
        roll = attack_roll(world, PLAYER, aid, stat='int')
        self.assertTrue(roll['critical'])
        roll.update(die=20, total=30)
        finish_spell(world, {'source': PLAYER, 'target': aid, 'roll': roll,
                            'effects': [{'kind': 'damage', 'amount': 1}]})
        self.assertEqual(world['actors'][aid]['rpg']['death_saves']['failure'], 2)

    def test_incapacitation_ends_concentration_and_harmless_casting_preserves_sanctuary(self):
        self.build(PLAYER, "cleric")
        player = self.sim.world["actors"][PLAYER]
        player["equipped"] = None
        player["rpg"]["prepared_by_class"]["cleric"] = ["ability.bless@1"]
        apply_effect(self.sim.world, PLAYER, PLAYER, {"kind": "condition", "condition": "sanctuary", "duration": 10})
        self.sim.command({"kind": "ability", "ability": "ability.bless@1", "target": PLAYER}, "bless")
        self.assertTrue(has_condition(self.sim.world, PLAYER, "sanctuary"))
        self.assertTrue(self.sim.world["actors"][PLAYER]["rpg"].get("concentration"))
        apply_effect(self.sim.world, "char.brakka", PLAYER, {"kind": "condition", "condition": "paralyzed", "duration": 2})
        self.assertFalse(self.sim.world["actors"][PLAYER]["rpg"].get("concentration"))
        self.assertFalse(any(e["origin"] == "ability.bless@1" for e in self.sim.world["effects"].values()))

    def test_materials_need_a_free_hand_and_shield_proficiency_limits_casting(self):
        self.build(PLAYER, "wizard")
        player = self.sim.world["actors"][PLAYER]
        shield = instantiate(self.sim.world, "itemdef.shield@1", {"carrier": PLAYER}, PLAYER)
        player["rpg"]["shield"] = shield["id"]
        player["rpg"]["cantrips"] = {"wizard": ["ability.light@1"]}
        before = deepcopy(self.sim.world)
        with self.assertRaises(ActionError):
            self.sim.command({"kind": "ability", "ability": "ability.light@1", "target": "item.sword"}, "untrained")
        self.assertEqual(self.sim.world, before)
        self.sim.world["actors"][PLAYER]["rpg"]["armor_proficiencies"].append("shield")
        self.sim.world["actors"][PLAYER]["equipped"] = "item.sword"
        with self.assertRaises(ActionError):
            self.sim.command({"kind": "ability", "ability": "ability.light@1", "target": "item.sword"}, "hands-full")
        self.sim.world["actors"][PLAYER]["equipped"] = None
        self.sim.command({"kind": "ability", "ability": "ability.light@1", "target": "item.sword"}, "light")
        self.assertIn("light", self.sim.world["items"]["item.sword"])

    def test_magic_missiles_respect_charm_and_sanctuary_before_damage(self):
        self.build(PLAYER, "wizard")
        self.sim.world["actors"][PLAYER]["rpg"]["prepared_by_class"]["wizard"] = ["ability.magic_missile@1"]
        target = "char.brakka"
        self.sim.world["actors"][target]["position"] = [24, 25]
        self.combat(PLAYER, [target])
        apply_effect(self.sim.world, target, PLAYER, {"kind": "condition", "condition": "charmed", "duration": 10})
        before = deepcopy(self.sim.world)
        with self.assertRaises(ActionError):
            self.sim.command({"kind": "ability", "ability": "ability.magic_missile@1", "target": target}, "charmed")
        self.assertEqual(self.sim.world, before)
        apply_effect(self.sim.world, target, PLAYER, {"kind": "remove_condition", "condition": "charmed"})
        apply_effect(self.sim.world, target, target, {"kind": "condition", "condition": "sanctuary", "duration": 10}, save_dc=40)
        hp = self.sim.world["actors"][target]["hp"]
        self.sim.command({"kind": "ability", "ability": "ability.magic_missile@1", "target": target}, "warded")
        self.assertEqual(self.sim.world["actors"][target]["hp"], hp)
        self.assertEqual(self.sim.world["actors"][PLAYER]["rpg"]["resources"]["slot_1"]["current"], 1)

    def test_recently_rested_or_distant_companion_does_not_cancel_player_recovery(self):
        from test_simulation import finish
        self.build(PLAYER, "fighter")
        target = "char.old_nessa"
        self.build(target, "cleric")
        self.sim.world["party"]["members"].append(target)
        self.sim.world["actors"][target]["position"] = [23, 24]
        self.sim.world["actors"][target]["rpg"]["long_rest_at"] = self.sim.world["tick"]
        self.sim.world["actors"][target]["hp"] = 4
        self.sim.world["actors"][PLAYER]["hp"] = 4
        finish(self.sim, {"kind": "long_rest"}, "rest")
        self.assertEqual(self.sim.world["actors"][PLAYER]["hp"], self.sim.world["actors"][PLAYER]["max_hp"])
        self.assertEqual(self.sim.world["actors"][target]["hp"], 4)

    def test_shield_reaction_saved_between_roll_and_damage(self):
        self.build(PLAYER, "fighter")
        self.build("char.brakka", "wizard")
        npc = self.sim.world["actors"]["char.brakka"]
        npc.update(position=[24, 25], hp=30, max_hp=30)
        npc["rpg"]["prepared_by_class"]["wizard"] = ["ability.shield@1"]
        self.sim.world["actors"][PLAYER]["stats"]["str"] = 18
        self.combat(PLAYER, ["char.brakka"])
        self.sim.world["rng"] = 1
        tick = self.sim.world["tick"]
        self.sim.command({"kind": "attack", "target": "char.brakka"}, "attack")
        self.assertEqual(self.sim.world["combat"]["pending"]["reactor"], "char.brakka")
        self.assertEqual(self.sim.world["actors"]["char.brakka"]["hp"], 30)
        self.sim = Simulation(json.loads(json.dumps(self.sim.world)))
        self.npc_reaction("char.brakka", "ability.shield@1")
        self.assertIsNone(self.sim.world["combat"]["pending"])
        self.assertEqual(self.sim.world["actors"]["char.brakka"]["hp"], 30)
        self.assertEqual(self.sim.world["actors"]["char.brakka"]["rpg"]["resources"]["slot_1"]["current"], 1)
        self.assertEqual(self.sim.world["tick"], tick)

    def test_protection_reaction_precedes_attack_dice(self):
        self.build("char.old_nessa", "fighter", style="protection")
        self.sim.world["party"]["members"].append("char.old_nessa")
        self.sim.world["actors"]["char.old_nessa"]["position"] = [23, 24]
        self.sim.world["actors"]["char.brakka"]["position"] = [24, 25]
        self.combat("char.brakka", [PLAYER])
        rng = self.sim.world["rng"]
        self.sim.command({"kind": "npc_turn", "actor": "char.brakka", "actions": [{"kind": "attack", "target": PLAYER}],
                          "mind_revision": self.sim.world["actors"]["char.brakka"]["mind_revision"]}, "attack")
        self.assertEqual(self.sim.world["rng"], rng)
        self.assertEqual(self.sim.world["combat"]["pending"]["kind"], "protection")
        self.npc_reaction("char.old_nessa", "feature.protection")
        attack = next(event for event in reversed(self.sim.world["events"]) if event["kind"] == "attack")
        self.assertEqual(attack["advantage"], -1)
        self.assertEqual(len(attack["rolls"]), 2)
        self.assertEqual(self.sim.world["combat"]["economy"]["char.old_nessa"]["reaction"], 0)

    def test_magic_missile_offers_shield_and_resumes_without_recasting(self):
        self.build(PLAYER, "wizard")
        self.build("char.brakka", "wizard")
        player, npc = self.sim.world["actors"][PLAYER], self.sim.world["actors"]["char.brakka"]
        player["rpg"]["prepared_by_class"]["wizard"] = ["ability.magic_missile@1"]
        npc["rpg"]["prepared_by_class"]["wizard"] = ["ability.shield@1"]
        npc.update(position=[24, 25], hp=30, max_hp=30)
        self.combat(PLAYER, [npc["id"]])
        self.sim.command({"kind": "ability", "ability": "ability.magic_missile@1", "target": npc["id"]}, "missiles")
        self.assertEqual(self.sim.world["combat"]["pending"]["kind"], "missiles")
        self.assertEqual(self.sim.world["actors"][npc["id"]]["hp"], 30)
        rng = self.sim.world["rng"]
        self.sim = Simulation(json.loads(json.dumps(self.sim.world)))
        self.npc_reaction(npc["id"], "ability.shield@1")
        self.assertEqual(self.sim.world["actors"][npc["id"]]["hp"], 30)
        self.assertEqual(self.sim.world["rng"], rng)
        self.assertEqual(self.sim.world["actors"][PLAYER]["rpg"]["resources"]["slot_1"]["current"], 1)

    def test_truce_needs_each_participant_and_aggression_cancels_earlier_agreement(self):
        self.build(PLAYER, "fighter")
        self.sim.world["actors"]["char.brakka"].update(position=[24, 25], hp=100, max_hp=100)
        self.combat(PLAYER, ["char.brakka"])
        self.sim.command({"kind": "offer_truce"}, "player-offer")
        self.assertIsNotNone(self.sim.world["combat"])
        aid = self.sim.world["combat"]["awaiting"]
        self.sim.command({"kind": "npc_turn", "actor": aid, "actions": [{"kind": "attack", "target": PLAYER}, {"kind": "end_turn"}],
            "mind_revision": self.sim.world["actors"][aid]["mind_revision"]}, "refuse")
        self.assertFalse(any(entry.get("peace_offer") for entry in self.sim.world["combat"]["participants"]))
        self.sim.command({"kind": "offer_truce"}, "renewed-offer")
        self.sim = Simulation(json.loads(json.dumps(self.sim.world)))
        aid = self.sim.world["combat"]["awaiting"]
        self.sim.command({"kind": "npc_turn", "actor": aid, "actions": [{"kind": "offer_truce"}],
            "mind_revision": self.sim.world["actors"][aid]["mind_revision"]}, "accept")
        self.assertIsNone(self.sim.world["combat"])
        self.assertEqual(self.sim.world["encounters"][-1]["outcome"], "truce")

    def test_spell_attack_keeps_invisible_advantage_then_expires_and_offers_shield(self):
        self.build(PLAYER, "wizard")
        self.build("char.brakka", "wizard")
        npc = self.sim.world["actors"]["char.brakka"]
        npc.update(position=[24, 25], hp=30, max_hp=30)
        npc["rpg"]["prepared_by_class"]["wizard"] = ["ability.shield@1"]
        self.combat(PLAYER, [npc["id"]])
        apply_effect(self.sim.world, PLAYER, PLAYER, {"kind": "condition", "condition": "invisible", "duration": 10}, breaks_on="attack_or_spell")
        self.sim.world["actors"][PLAYER]["stats"]["int"] = 18
        self.sim.world["rng"] = 1
        self.sim.command({"kind": "ability", "ability": "ability.fire_bolt@1", "target": npc["id"]}, "bolt")
        pending = self.sim.world["combat"]["pending"]
        self.assertEqual(pending["kind"], "spell")
        # Nearby hostile cancels unseen-attacker advantage for a ranged attack.
        self.assertEqual(pending["roll"]["advantage"], 0)
        self.assertFalse(has_condition(self.sim.world, PLAYER, "invisible"))
        before = deepcopy(self.sim.world)
        restored = Simulation(json.loads(json.dumps(before)))
        self.npc_reaction(npc["id"])
        restored.command({"kind": "npc_reaction", "actor": npc["id"], "ability": None, "mind_revision": before["actors"][npc["id"]]["mind_revision"]}, "reaction")
        self.assertEqual(self.sim.world, restored.world)

    def test_missiles_kill_once_without_invalidating_remaining_darts(self):
        self.build(PLAYER, "wizard")
        self.sim.world["actors"][PLAYER]["rpg"]["prepared_by_class"]["wizard"] = ["ability.magic_missile@1"]
        npc = self.sim.world["actors"]["char.brakka"]
        npc.update(position=[24, 25], hp=1)
        self.combat(PLAYER, [npc["id"]])
        self.sim.command({"kind": "ability", "ability": "ability.magic_missile@1", "target": npc["id"]}, "fatal")
        self.assertEqual(self.sim.world["actors"][npc["id"]]["life"], "dead")
        self.assertEqual(len([event for event in self.sim.world["events"] if event["kind"] == "death" and event["actor"] == npc["id"]]), 1)

    def test_movement_waits_for_all_opportunities_and_resumes_exactly_once(self):
        self.sim.world["actors"]["char.brakka"]["position"] = [24, 25]
        self.sim.world["actors"]["char.tommen_ash"]["position"] = [25, 24]
        self.combat(PLAYER, ["char.brakka", "char.tommen_ash"])
        self.sim.command({"kind": "move", "position": [23, 24]}, "move")
        self.assertEqual(self.sim.world["actors"][PLAYER]["position"], [24, 24])
        self.npc_reaction("char.brakka", op="first-pass")
        self.assertEqual(self.sim.world["actors"][PLAYER]["position"], [24, 24])
        self.sim = Simulation(json.loads(json.dumps(self.sim.world)))
        self.npc_reaction("char.tommen_ash", op="second-pass")
        self.assertEqual(self.sim.world["actors"][PLAYER]["position"], [23, 24])
        moves = [event for event in self.sim.world["events"] if event["kind"] == "move" and event["actor"] == PLAYER]
        self.assertEqual(len(moves), 1)

    def test_physical_letter_contents_are_not_perceived_before_reading(self):
        self.build(PLAYER, "rogue")
        player = self.sim.world["actors"][PLAYER]
        paper = next(item for item in self.sim.world["items"].values() if item["kind"] == "paper" and item["place"].get("carrier") == PLAYER)
        self.sim.world["actors"]["char.old_nessa"]["position"] = [23, 24]
        self.sim.command({"kind": "write", "target": paper["id"], "text": "SEALED_PRIVATE_TESTIMONY"}, "write")
        self.sim.command({"kind": "give", "target": paper["id"], "recipient": "char.old_nessa"}, "give")
        view = knowledge(self.sim.world, "char.old_nessa")
        self.assertNotIn("SEALED_PRIVATE_TESTIMONY", json.dumps(view))
        from mythfall.simulation.actions import apply_action
        apply_action(self.sim.world, "char.old_nessa", {"kind": "read", "target": paper["id"], "open": True})
        self.assertIn("SEALED_PRIVATE_TESTIMONY", json.dumps(knowledge(self.sim.world, "char.old_nessa")))
        self.assertNotIn("SEALED_PRIVATE_TESTIMONY", json.dumps(knowledge(self.sim.world, "char.tommen_ash")))

    def test_invisibility_and_concentration_change_observation_without_rewinding_consequences(self):
        self.build(PLAYER, "wizard")
        self.sim.world["actors"][PLAYER]["rpg"]["xp"] = 900
        self.build(PLAYER, "wizard")
        self.build(PLAYER, "wizard", spells=["ability.invisibility@1", "ability.hold_person@1"])
        player = self.sim.world["actors"][PLAYER]
        player["rpg"]["prepared_by_class"]["wizard"] = ["ability.invisibility@1", "ability.detect_magic@1"]
        self.sim.command({"kind": "ability", "ability": "ability.invisibility@1", "target": PLAYER}, "invisible")
        self.assertFalse(can_identify(self.sim.world, "char.old_nessa", PLAYER))
        self.sim.command({"kind": "drop", "target": "item.sword"}, "drop")
        self.assertEqual(self.sim.world["items"]["item.sword"]["place"], {"ground": [24, 24]})
        self.sim.command({"kind": "ability", "ability": "ability.detect_magic@1"}, "other-concentration")
        self.assertFalse(has_condition(self.sim.world, PLAYER, "invisible"))
        self.assertTrue(can_identify(self.sim.world, "char.old_nessa", PLAYER))
        self.assertEqual(self.sim.world["items"]["item.sword"]["place"], {"ground": [24, 24]})

    def test_declared_ruling_consumes_one_check_and_rejects_an_unsupported_capability(self):
        self.build(PLAYER, "rogue")
        self.sim.world["fixtures"]["fixture.hinge"] = {"id": "fixture.hinge", "name": "Rusty hinge", "position": [25, 24], "hp": 5}
        ruling = {"name": "Free the hinge", "reason": "The hinge is visibly corroded.", "stakes": "A successful Athletics check will break the damaged hinge.",
                  "context": "Rusty hinge, first attempt", "capability": {"kind": "body"}, "targets": ["fixture.hinge"], "range": 1,
                  "check": {"skill": "athletics", "difficulty": 1}, "success": [{"kind": "object_damage", "amount": 5}], "failure": [], "economy": "action"}
        command = {"kind": "dm_tools", "operations": [{"kind": "ruling", "ruling": ruling}]}
        self.sim.command(command, "ruling")
        self.assertEqual(self.sim.world["fixtures"]["fixture.hinge"]["hp"], 0)
        self.assertEqual(len(self.sim.world["rulings"]), 1)
        self.assertEqual(len([event for event in self.sim.world["events"] if event["kind"] == "check"]), 1)
        before = deepcopy(self.sim.world)
        with self.assertRaises(ActionError):
            self.sim.command(command, "same-circumstances")
        self.assertEqual(before, self.sim.world)
        ruling.update(context="Invent teleportation", targets=[PLAYER], success=[{"kind": "move", "teleport": True, "position": [25, 24]}])
        with self.assertRaisesRegex(ActionError, "teleport"):
            self.sim.command(command, "teleport")
        self.assertEqual(before, self.sim.world)


if __name__ == "__main__":
    unittest.main()
