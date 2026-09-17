from copy import deepcopy
import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from RealmEngine.modules import ModuleActionContext, ModuleMessageContext
from mythfall.simulation.presentation import packet
from mythfall.simulation.state import ActionError, PLAYER
from mythfall.simulation.store import WorldStore
from mythfall.world_agent import handle_message, knowledge
from mythfall.world_runtime import execute_world_action
from test_world_agent import ModelFixture, action


def mechanics(world):
    return {key: value for key, value in world.items() if key not in {"game_chat", "receipts"}}


class GameChatTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name)
        (self.workspace / "state.json").write_text('{"state":"play","active_agent":"dm","player_character_id":"char.player"}')
        self.store = WorldStore(self.workspace)
        self.store.ensure()

    def context(self, operation, intent, revision=None):
        return ModuleActionContext(module_id="mythfall", session_uuid="00000000-0000-0000-0000-000000000001", realm_id="Mythfall",
            archive_user_id=None, realm_session_id=None, workspace_root=self.workspace.parent,
            workspace_path=self.workspace, logger=logging.getLogger("test"), operation_id=operation,
            payload={"intent": intent, "expected_revision": self.store.read()["revision"] if revision is None else revision})

    def run_action(self, operation, intent, **kwargs):
        return execute_world_action(self.context(operation, intent, **kwargs))

    def test_inventory_actions_and_retry_commit_one_ordered_transcript_with_effects(self):
        intent = {"kind": "drop", "target": "item.sword"}
        context = self.context("drop", intent)
        update = execute_world_action(context)
        after = self.store.read()
        self.assertEqual(update["chat"], after["game_chat"])
        self.assertEqual(after["items"]["item.sword"]["place"], {"ground": [24, 24]})
        self.assertEqual(update["chat"]["turns"][0]["player"], "Drop Iron sword.")
        self.assertIn("leaves Iron sword on the ground", update["chat"]["turns"][0]["messages"][0]["text"])
        self.assertEqual(execute_world_action(context)["chat"], update["chat"])
        self.assertEqual(self.store.read(), after)
        with self.assertRaises(ActionError):
            self.run_action("drop", {"kind": "drop", "target": "item.lantern"})
        self.assertEqual(self.store.read(), after)
        self.run_action("take", {"kind": "take", "target": "item.sword"})
        self.assertEqual([t["id"] for t in self.store.read()["game_chat"]["turns"]], ["drop", "take"])

    def test_rejected_intent_is_saved_without_changing_mechanics_or_retried_inference(self):
        before = self.store.read()
        model = ModelFixture({"mode": "action", "action": action("move", position=[60, 40]), "target": None, "text": "Teleport."})
        context = self.context("rejected", {"kind": "ask", "text": "Teleport me."})
        with patch("mythfall.world_models.openai_client", return_value=model):
            update = execute_world_action(context)
            execute_world_action(context)
        self.assertEqual(update["result"]["reason"], "rejected")
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(mechanics(self.store.read()), mechanics(before))
        self.assertEqual(update["chat"]["turns"][0]["player"], "Teleport me.")
        self.assertEqual(WorldStore(self.workspace).read()["game_chat"], update["chat"])

    def test_uncertain_model_call_is_visible_and_cannot_be_repeated_by_operation_id(self):
        before = self.store.read()
        model = ModelFixture()
        context = self.context("uncertain", {"kind": "talk", "target": "char.old_nessa", "text": "Hello."})
        with patch("mythfall.world_models.openai_client", return_value=model):
            first = execute_world_action(context)
            second = execute_world_action(context)
        self.assertEqual(first, second)
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(mechanics(self.store.read()), mechanics(before))
        self.assertIn("could not finish", first["chat"]["turns"][0]["summary"])

    def test_npc_speech_and_freeform_answers_share_history_without_private_traces(self):
        npc = ModelFixture({"speech": "Good morning, traveler.", "actions": [], "reason": "A polite greeting.", "promise": None, "horizon_ticks": 10})
        with patch("mythfall.world_models.openai_client", return_value=npc):
            update = self.run_action("talk", {"kind": "talk", "target": "char.old_nessa", "text": "Good morning."})
        messages = update["chat"]["turns"][0]["messages"]
        self.assertEqual([(m["speaker"], m["text"]) for m in messages if m["speaker"] == "Old Nessa"], [("Old Nessa", "Good morning, traveler.")])
        before = self.store.read()
        model = ModelFixture({"mode": "answer", "action": None, "target": None, "text": "Your sword is in your pack."})
        with patch("mythfall.world_models.openai_client", return_value=model):
            update = self.run_action("question", {"kind": "ask", "text": "Where is my sword?"})
        self.assertEqual(update["world"]["tick"], before["tick"])
        self.assertEqual(update["chat"]["turns"][-1]["summary"], "Your sword is in your pack.")
        self.assertNotIn("response.fixture", json.dumps(update["chat"]))
        self.assertNotIn("game_chat", knowledge(self.store.read(), "char.old_nessa"))

    def test_activity_continuations_and_pause_update_one_saved_turn(self):
        intent = {"kind": "wait", "ticks": 1000, "activity": "rest"}
        first, _ = self.store.execute(intent, "rest", chunk_ticks=2)
        self.assertEqual(first["reason"], "yielded")
        resumed, _ = WorldStore(self.workspace).execute({"kind": "resume", "wait_id": "rest"}, "resume", chunk_ticks=3)
        before_cancel = self.store.read()
        cancelled = self.run_action("pause", {"kind": "cancel", "wait_id": "rest"})
        turns = cancelled["chat"]["turns"]
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["id"], "rest")
        self.assertIn("Activity paused. 30 seconds passed.", turns[0]["summary"])
        self.assertEqual(cancelled["world"]["tick"], before_cancel["tick"])
        self.assertEqual(len({m["id"] for m in turns[0]["messages"]}), len(turns[0]["messages"]))
        self.assertEqual(resumed["elapsed_ticks"], 3)

    def test_old_snapshot_and_restore_keep_history_consistent_without_migration_effects(self):
        legacy = self.store.read()
        self.assertEqual(packet(legacy)["chat"], {"revision": 0, "turns": []})
        self.run_action("step", {"kind": "wait", "ticks": 1})
        with self.store.locked():
            self.store.save(deepcopy(legacy))
        self.assertEqual(self.store.read(), legacy)
        self.assertEqual(packet(self.store.read())["chat"]["turns"], [])

    def test_existing_chat_in_play_joins_game_history_through_the_same_boundary(self):
        action_context = self.context("unused", {})
        context = ModuleMessageContext(**{key: getattr(action_context, key) for key in (
            "module_id", "session_uuid", "realm_id", "archive_user_id", "realm_session_id", "workspace_root", "workspace_path", "logger")},
            message_id=42, player_message="What am I carrying?", messages=[], script_repair_attempts=0)
        model = ModelFixture({"mode": "answer", "action": None, "target": None, "text": "You have an iron sword."})
        with patch("mythfall.world_models.openai_client", return_value=model), patch("RealmEngine.networking.send_message"):
            handle_message(context)
        turns = self.store.read()["game_chat"]["turns"]
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["id"], "chat-42")
        self.assertEqual(turns[0]["player"], "What am I carrying?")
        self.assertEqual(turns[0]["summary"], "You have an iron sword.")

    def test_stale_request_is_a_rejection_and_never_reveals_hidden_names(self):
        self.run_action("step", {"kind": "wait", "ticks": 1})
        before = self.store.read()
        update = self.run_action("stale", {"kind": "take", "target": "item.hidden_secret"}, revision=0)
        self.assertEqual(update["result"]["reason"], "rejected")
        self.assertEqual(mechanics(self.store.read()), mechanics(before))
        self.assertEqual(update["chat"]["turns"][-1]["player"], "Pick up that target.")


if __name__ == "__main__":
    unittest.main()
