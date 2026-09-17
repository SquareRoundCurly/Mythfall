"""Mythfall's installed world boundary for chat and direct player controls."""

import re
from copy import deepcopy

from RealmEngine import networking
from .realm_state import load_realm_runtime_state
from .simulation.presentation import packet, write_project
from .simulation.state import ActionError, fingerprint, require
from .simulation.store import WorldStore
from .game_chat import record_result

PLAYER_ACTIONS = {"move", "travel", "take", "drop", "equip", "give", "use", "speak", "inspect", "check",
                  "attack", "wait", "resume", "cancel", "talk", "ask", "ability", "choose_class", "prepare", "unequip", "copy_spell",
                  "recruit", "dismiss", "order", "short_rest", "long_rest", "end_turn", "reaction", "retreat", "continue_combat",
                  "dodge", "dash", "disengage", "hide", "stand", "help", "offhand", "climb", "write", "read", "put", "loot", "traverse", "attune", "refuel", "resolve_events", "offer_truce"}


def setup_world(context):
    if load_realm_runtime_state(context.workspace_path).state != "play":
        return None
    store = WorldStore(context.workspace_path)
    world = store.ensure()
    if not world.get("adventure_version"):
        from .simulation.adventure import install
        with store.locked():
            world = install(store.read())
            store.save(world)
    write_project(context.workspace_path, world)
    return world


def observe_world(context):
    state = load_realm_runtime_state(context.workspace_path)
    if state.state != "play":
        return {"status": "initializing", "message": "Create your character in Chat to enter Emberwick."}
    return packet(WorldStore(context.workspace_path).read())


def execute_world_action(context):
    require(load_realm_runtime_state(context.workspace_path).state == "play", "Finish creating your character before entering the world.")
    payload = context.payload
    intent = payload.get("intent", {})
    require(isinstance(context.operation_id, str) and re.fullmatch(r"[A-Za-z0-9._:-]{1,120}", context.operation_id),
            "A stable operation ID is required.")
    require(isinstance(intent, dict), "An intent must be an object.")
    require(intent.get("kind") in PLAYER_ACTIONS, "That action is unavailable to the player.")
    revision = payload.get("expected_revision")
    require(type(revision) is int and revision >= 0, "An observed world revision is required.")
    store = WorldStore(context.workspace_path)
    with store.locked():
        world = store.read()
        previous = world["receipts"].get(context.operation_id)
        if previous:
            require(previous["intent"] == fingerprint(intent), "That operation ID belongs to another request.")
            return publish_world(context, world, deepcopy(previous["result"]))
    try:
        return _resolve(context, intent, revision)
    except ActionError as error:
        # Rejections are durable receipts too, but do not change the simulation
        # revision, clock, RNG, or entities. Retrying cannot pay for inference or
        # turn a previously rejected request into a later successful action.
        with store.locked():
            before = store.read()
            previous = before["receipts"].get(context.operation_id)
            if previous:
                require(previous["intent"] == fingerprint(intent), "That operation ID belongs to another request.")
                return publish_world(context, before, deepcopy(previous["result"]))
            world = deepcopy(before)
            result = {"reason": "rejected", "message": str(error), "operation_id": context.operation_id,
                      "tick": world["tick"], "revision": world["revision"], "elapsed_ticks": 0,
                      "elapsed_seconds": 0, "events": []}
            world["receipts"][context.operation_id] = {"intent": fingerprint(intent), "result": deepcopy(result)}
            record_result(before, world, intent, context.operation_id, result)
            store.save(world)
        return publish_world(context, world, result)


def _resolve(context, intent, revision):
    if intent["kind"] == "continue_combat":
        from .world_agent import combat_decision
        return combat_decision(context, revision)
    if intent["kind"] == "ask":
        from .world_agent import interpret
        update, reply = interpret(context)
        update["reply"] = reply
        return update
    if intent["kind"] in {"talk", "order"} and (intent["kind"] == "talk" or not WorldStore(context.workspace_path).read()["combat"]):
        from .world_agent import converse
        return converse(context, intent, revision)
    result, world = WorldStore(context.workspace_path).execute(intent, context.operation_id, expected_revision=revision)
    return publish_world(context, world, result)


def publish_world(context, world, result):
    write_project(context.workspace_path, world)
    update = packet(world)
    update["result"] = result
    networking.publish_event(context, "realm.world.changed", update)
    return update


def open_adventure(context):
    world = setup_world(context)
    name = world["actors"]["char.player"]["name"]
    networking.send_message(context, role="assistant", label="DM", body=(
        f"Welcome to Emberwick, {name}. Rain-dark cobbles surround an old well, and Old Nessa "
        "tends her herbs nearby. The Stonebridge Inn stands to the east.\n\n"
        "Choose a class in Character to receive its starting abilities and equipment. Mara needs the Crowglass survey ledger; "
        "the Journal records the leads, and Ellis at the shrine may be willing to accompany you. "
        "Your sword and lantern are in your pack. Move with the arrow keys or click the map; "
        "drag the map to look around and select someone to talk. Describe any action in Game chat, or use the world controls "
        "to wait, rest, and watch for something to happen. Time advances only when you act."
    ))
    networking.publish_event(context, "workspace.changed", {"path": "game.json", "kind": "file", "operation": "write"})
    networking.publish_event(context, "realm.world.changed", packet(world))
