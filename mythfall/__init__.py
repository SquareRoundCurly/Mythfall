"""Mythfall realm module."""

from importlib.metadata import PackageNotFoundError, version as _package_version
from pathlib import Path

from RealmEngine import networking
from RealmEngine.modules import ModuleBase, RealmCatalogEntry, RealmStateDefinition


MODULE_ID = "mythfall"
MODULE_NAME = "Mythfall"
try:
    MODULE_VERSION = _package_version("mythfall")
except PackageNotFoundError:
    MODULE_VERSION = "0.0.0"
SEED_PATH = Path(__file__).resolve().parent / "seed"
WORKSPACE_DIR_NAME = "Mythfall"
INITIAL_STATE = "initializing"


class MythfallModule(ModuleBase):
    id = MODULE_ID
    name = MODULE_NAME
    version = MODULE_VERSION
    realm_ids = ["Mythfall"]
    default_realm_id = "Mythfall"
    workspace_dir_name = WORKSPACE_DIR_NAME
    seed_path = SEED_PATH
    initial_state = INITIAL_STATE

    def realm_catalog(self):
        return [
            RealmCatalogEntry(
                realm_id="Mythfall",
                title="Mythfall",
                summary="A living Emberwick: persistent possessions, thoughtful villagers, and time that moves when you act.",
            ),
        ]

    def state_definitions(self):
        return {
            "initializing": RealmStateDefinition(
                id="initializing",
                agent="character_creator",
                initial_message=(
                    "Welcome to Mythfall. Before the realm begins, describe the "
                    "character you want to play. A name, a vibe, what they are "
                    "good at, and what kind of trouble they are walking toward "
                    "is enough."
                ),
                next=["play", "ended"],
            ),
            "play": RealmStateDefinition(
                id="play",
                agent="dm",
                next=["ended"],
            ),
            "ended": RealmStateDefinition(
                id="ended",
                agent=None,
                next=[],
            ),
        }

    def on_setup(self, context):
        from mythfall.realms import copy_realm_seed, load_realm

        seed_realm = load_realm(self.seed_path)
        context.workspace_path.parent.mkdir(parents=True, exist_ok=True)
        copy_realm_seed(seed_realm, context.workspace_path)
        self._send_initial_message(context)

    def on_session_load(self, context):
        from mythfall.realms import copy_realm_seed, load_realm, maybe_load_realm
        from mythfall.realm_state import ensure_realm_runtime_state

        seed_realm = load_realm(self.seed_path)
        workspace_realm = maybe_load_realm(context.workspace_path)
        if workspace_realm is None or workspace_realm.version != seed_realm.version:
            return

        copy_realm_seed(seed_realm, context.workspace_path)
        ensure_realm_runtime_state(context.workspace_path)
        from mythfall.world_runtime import setup_world
        setup_world(context)

    def on_message(self, context):
        from mythfall.realm_state import load_realm_runtime_state
        if load_realm_runtime_state(context.workspace_path).state == "play":
            from mythfall.world_agent import handle_message
            return handle_message(context)
        from mythfall.runtime import handle_message

        handle_message(context)

    def on_observe(self, context):
        from mythfall.world_runtime import observe_world
        return observe_world(context)

    def on_action(self, context):
        from mythfall.world_runtime import execute_world_action
        return execute_world_action(context)

    def on_component_action(self, context):
        from mythfall.runtime import handle_component_action

        handle_component_action(context)

    def _send_initial_message(self, context):
        from mythfall.llm import generate_reply
        from mythfall.realm_state import (
            active_agent_config_path,
            active_state_definition,
            ensure_realm_runtime_state,
        )

        ensure_realm_runtime_state(context.workspace_path)
        state_definition = active_state_definition(context.workspace_path)
        label = (
            "Character Creator"
            if state_definition and state_definition.agent == "character_creator"
            else None
        )

        try:
            created_reply = generate_reply(
                [],
                agent_config_path=active_agent_config_path(context.workspace_path),
                workspace_path=context.workspace_path,
                hook="on_created",
            )
        except Exception:
            created_reply = None

        if created_reply and created_reply.visible_events:
            for visible_event in created_reply.visible_events:
                networking.send_message(
                    context,
                    body=visible_event.body,
                    role="assistant",
                    label=visible_event.speaker,
                    event_type=visible_event.event_type,
                    component=visible_event.component,
                    payload=visible_event.payload,
                )
            return

        initial_message = (
            state_definition.initial_message
            if state_definition is not None
            else None
        )
        if not initial_message:
            return

        networking.send_message(
            context,
            body=initial_message,
            role="assistant",
            label=label,
        )


__all__ = [
    "MythfallModule",
    "MODULE_ID",
    "MODULE_NAME",
    "MODULE_VERSION",
    "SEED_PATH",
    "WORKSPACE_DIR_NAME",
    "INITIAL_STATE",
]
