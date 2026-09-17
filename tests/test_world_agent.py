import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from RealmEngine.modules import ModuleActionContext
from mythfall.simulation.state import ActionError, PLAYER
from mythfall.simulation.store import WorldStore
from mythfall.world_agent import converse, interpret, knowledge
from mythfall.world_models import Intent


def action(kind, **fields):
    return {**{key: None for key in Intent.model_fields}, "kind": kind, **fields}


class ModelFixture:
    def __init__(self, output=None, callback=None):
        self.output, self.callback, self.calls = output, callback, []
        self.responses = self

    def create(self, **request):
        self.calls.append(request)
        if self.callback:
            self.callback(request)
        if self.output is None:
            raise TimeoutError("fixture timeout")
        return SimpleNamespace(status="completed", output_text=json.dumps(self.output), id="response.fixture", usage=None)


class WorldAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        (self.workspace / "state.json").write_text('{"state":"play","active_agent":"dm","player_character_id":"char.player"}')
        self.store = WorldStore(self.workspace)
        self.store.ensure()

    def context(self, operation, intent):
        return ModuleActionContext(module_id="mythfall", session_uuid="00000000-0000-0000-0000-000000000001", realm_id="Mythfall",
                                   archive_user_id=None, realm_session_id=None, workspace_root=self.workspace.parent,
                                   workspace_path=self.workspace, logger=logging.getLogger("test"), operation_id=operation,
                                   payload={"intent": intent, "expected_revision": self.store.read()["revision"]})

    def collect_sword(self):
        self.store.execute({"kind": "drop", "target": "item.sword"}, "drop")
        self.store.execute({"kind": "wait", "ticks": 10, "until": {"kind": "item_taken", "target": "item.sword"}}, "watch")
        self.assertEqual(self.store.read()["items"]["item.sword"]["place"], {"carrier": "char.old_nessa"})

    def test_npc_conversation_returns_the_same_sword_and_retries_without_inference(self):
        self.collect_sword()
        before = self.store.read()
        speech = "I kept your sword safe. I'll hand it back now."
        model = ModelFixture({"speech": speech, "actions": [action("travel", target=PLAYER, adjacent=True),
                                                                  action("give", target="item.sword", recipient=PLAYER)],
                              "reason": "Return the traveler's observed lost property.", "promise": "I will return your sword.", "horizon_ticks": 100},
                             callback=lambda _: self.assertEqual(self.store.read(), before))
        intent = {"kind": "talk", "target": "char.old_nessa", "text": "Please return the sword you picked up."}
        context = self.context("return", intent)
        result = converse(context, intent, before["revision"], client=model)
        after = self.store.read()
        self.assertEqual(after["tick"], before["tick"] + 1)
        self.assertEqual(after["items"]["item.sword"]["place"], {"carrier": PLAYER})
        self.assertTrue(any(m["kind"] == "promise" for m in after["actors"]["char.old_nessa"]["memories"]))
        self.assertEqual(converse(context, intent, before["revision"], client=model)["result"], result["result"])
        self.assertEqual(self.store.read(), after)
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(model.calls[0]["model"], "gpt-6-astra")
        self.assertEqual(model.calls[0]["timeout"], 90)

    def test_unknown_provider_outcome_does_not_consume_time_or_repeat_call(self):
        before = self.store.read()
        intent = {"kind": "talk", "target": "char.old_nessa", "text": "Hello."}
        context = self.context("timeout", intent)
        model = ModelFixture()
        for _ in range(2):
            with self.assertRaises(ActionError):
                converse(context, intent, before["revision"], client=model)
        self.assertEqual(self.store.read(), before)
        self.assertEqual(len(model.calls), 1)

    def test_distant_conversation_is_rejected_before_inference(self):
        model = ModelFixture()
        intent = {"kind": "talk", "target": "char.brakka", "text": "Hello."}
        with self.assertRaises(ActionError):
            converse(self.context("far", intent), intent, 0, client=model)
        self.assertEqual(model.calls, [])

    def test_language_wait_uses_observable_runtime_condition_and_is_idempotent(self):
        self.store.execute({"kind": "drop", "target": "item.sword"}, "drop")
        model = ModelFixture({"mode": "action", "action": action("wait", ticks=600, activity="watch",
                                 until={"kind": "item_taken", "target": "item.sword", "event": None}), "target": None,
                              "text": "Watch for someone taking the sword, for at most one hour."})
        context = self.context("language-watch", {"kind": "ask", "text": "Watch until someone picks up my sword."})
        update, _ = interpret(context, client=model)
        self.assertEqual(update["result"]["reason"], "condition_reached")
        self.assertEqual(update["world"]["tick"], 4803)
        after = self.store.read()
        interpret(context, client=model)
        self.assertEqual(self.store.read(), after)
        self.assertEqual(len(model.calls), 1)

    def test_interpreter_cannot_teleport_or_advance_time_on_rejection(self):
        before = self.store.read()
        model = ModelFixture({"mode": "action", "action": action("move", position=[60, 40]), "target": None,
                              "text": "Teleport to the mine."})
        with self.assertRaises(ActionError):
            interpret(self.context("teleport", {"kind": "ask", "text": "Teleport me."}), client=model)
        self.assertEqual(self.store.read(), before)

    def test_an_answer_costs_no_world_time(self):
        before = self.store.read()
        model = ModelFixture({"mode": "answer", "action": None, "target": None, "text": "You carry an iron sword and a brass lantern."})
        update, text = interpret(self.context("inventory", {"kind": "ask", "text": "What's in my pack?"}), client=model)
        self.assertEqual(update["world"]["tick"], before["tick"])
        self.assertIn("sword", text)
        self.assertEqual(self.store.read()["rng"], before["rng"])

    def test_npc_observation_excludes_unseen_inventory_and_private_facts(self):
        world = self.store.read()
        world["actors"]["char.brakka"]["lore"] = "UNSEEN_SECRET"
        world["items"]["item.sword"]["place"] = {"carrier": "char.brakka"}
        view = knowledge(world, "char.old_nessa")
        self.assertNotIn("UNSEEN_SECRET", json.dumps(view))
        self.assertNotIn("item.sword", {i["id"] for i in view["items"]})

    def test_character_creation_never_executes_a_legacy_turn_script(self):
        from mythfall.runtime import _generate_creation_reply
        from mythfall.llm import LLMReply
        from mythfall.turns import begin_turn
        turn = begin_turn(session_uuid="fixture", workspace_path=self.workspace, player_message="Create Rowan")
        (turn.path / "script.py").write_text("raise RuntimeError('must never execute')")
        reply = LLMReply(text="Character notes.", response_id=None, tool_traces=[], visible_events=[])
        with patch("mythfall.runtime.generate_reply", return_value=reply):
            actual, script_ran = _generate_creation_reply(context=self.context("creation", {}), recent_messages=[],
                                                         agent_config_path=self.workspace, turn=turn)
        self.assertIs(actual, reply)
        self.assertFalse(script_ran)

    def test_migration_preserves_authored_character_and_prior_scene(self):
        from mythfall.simulation.presentation import write_project
        from mythfall.simulation.seed import new_world
        directory = self.workspace / "characters"
        directory.mkdir()
        character = "---\nid: char.player\nname: Aster\nstats: {str: 12, dex: 17, con: 10, int: 13, wis: 8, cha: 14}\nhp: {current: 7, max: 12}\nlocation: locations/lowmere/emberwick/stonebridge_inn/common_room.md\n---\nOriginal history.\n"
        (directory / "player.md").write_text(character)
        (self.workspace / "game.json").write_text('{"version":1,"scene":"custom.json"}')
        world = new_world(self.workspace)
        write_project(self.workspace, world)
        self.assertEqual(world["actors"][PLAYER]["name"], "Aster")
        self.assertEqual(world["actors"][PLAYER]["stats"]["dex"], 17)
        self.assertEqual(world["actors"][PLAYER]["hp"], 7)
        self.assertEqual((directory / "player.md").read_text(), character)
        self.assertEqual(json.loads((self.workspace / "state" / "legacy-game.json").read_text())["scene"], "custom.json")


if __name__ == "__main__":
    unittest.main()
