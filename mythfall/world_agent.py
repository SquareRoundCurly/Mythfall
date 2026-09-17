"""Language proposes intents; installed simulation code owns every effect."""

from copy import deepcopy
import json

from RealmEngine import networking
from .game_chat import record_result
from .simulation.actions import apply_action
from .simulation.engine import Simulation
from .simulation.perception import observe
from .simulation.state import ActionError, PLAYER, fingerprint, require
from .simulation.store import WorldStore
from .turns import begin_turn
from .world_models import Interpretation, NPCDecision, CombatDecision, decide
from .simulation.minds import resolve_reference, reference
from .simulation.characters import prepared_abilities

from .rpg_prompts import RULES, DM as INTERPRETER, NPC, COMBAT, TOOLS


def knowledge(world, actor_id):
    result = observe(world, actor_id)
    result["events"] = result["events"][-24:]
    result["self"]["memories"] = result["self"]["memories"][-32:]
    result["places"] = {key: {"name": value["name"], "center": value["center"]}
                        for key, value in world["map"]["places"].items()}
    result["abilities"] = [deepcopy(world["definitions"][key]) for key in prepared_abilities(world, actor_id)]
    result["equipment_rules"] = {item["definition"]: deepcopy(world["definitions"][item["definition"]])
                                 for item in result["items"] if item.get("definition")}
    return result


def dm_context(world):
    """Private adjudication context is never passed to an NPC handoff."""
    from .simulation.catalog import CLASSES
    from .simulation.effects import FIELDS, REQUIRED
    return {"adventure": deepcopy(world.get("adventure", {})), "quests": deepcopy(world["quests"]),
            "classes": CLASSES, "definitions": deepcopy(world["definitions"]),
            "recent_canonical_events": [{key: deepcopy(value) for key, value in event.items() if key != "perceptions"} for event in world["events"][-24:]],
            "recent_rulings": list(deepcopy(world["rulings"]).values())[-12:],
            "schedules": deepcopy(world["schedules"]), "tools": TOOLS,
            "effects": {kind: {"fields": sorted(fields), "required": sorted(REQUIRED.get(kind, set()))} for kind, fields in FIELDS.items()},
            "acquisition_causes": [{"sequence": event["sequence"], "kind": event["kind"], "text": event["text"]}
                                    for event in world["events"][-80:] if event["kind"] in {"discovery", "training", "quest_complete", "encounter_end", "give", "read", "check", "ruling"}]}


def validate_plan(view, actions):
    known = {a["id"] for a in view["actors"]} | {i["id"] for i in view["items"]}
    known |= set(view["self"]["known"]) | set(view["doors"]) | set(view["places"])
    known |= set(view.get("fixtures", {})) | set(view.get("links", {}))
    for action in actions:
        require(action["kind"] not in {"wait", "move"}, "NPC plans use travel and bounded ordinary actions.")
        for field in ("target", "recipient"):
            require(not action.get(field) or action[field] in known, "An NPC plan refers to something that character does not know.")
        if action["kind"] == "attack":
            require(view["self"]["relationships"].get(action.get("target"), 0) <= -5,
                    "That character has no established hostility toward the proposed opponent.")


def converse(context, intent, revision, *, client=None, interpreted=None, handoffs=None):
    from .world_runtime import publish_world

    require(isinstance(intent.get("text"), str) and 0 < len(intent["text"].strip()) <= 1200,
            "Say between 1 and 1200 characters.")
    store = WorldStore(context.workspace_path)
    with store.locked():
        world = store.read()
        public_request = interpreted["request"] if interpreted else intent
        previous = world["receipts"].get(context.operation_id)
        if previous:
            require(previous["intent"] == fingerprint(public_request), "That operation ID belongs to another request.")
            return publish_world(context, world, deepcopy(previous["result"]))
        require(world["revision"] == revision, "The world has changed. Observe it again before speaking.")
        require(world["combat"] is None, "Resolve the encounter before starting a conversation.")
        require(world["pending"] is None or world["pending"]["status"] != "running", "Pause the current activity before speaking.")
        # Trial delivery builds each recipient's actual perception before any
        # handoff. The entire conversation still commits once, after decisions.
        trial = deepcopy(world)
        _, spoken = apply_action(trial, PLAYER, {**intent, "kind": "speak"})
        target = resolve_reference(world, PLAYER, intent.get("target"))
        require(target is None or target in world["actors"] and target != PLAYER, "Choose an NPC to talk with.")
        if intent["kind"] == "order":
            require(target in world["party"]["members"], "Give orders to a companion.")
        selected = handoffs if handoffs is not None else ([target] if target else [])
        selected = [resolve_reference(world, PLAYER, aid) for aid in selected]
        require(len(selected) <= 2 and len(set(selected)) == len(selected), "At most two distinct NPC handoffs per conversation.")
        eligible = set(spoken["perceptions"]) - {PLAYER}
        require(set(selected) <= eligible, "A selected NPC cannot receive that communication.")
        responses = []
        for index, aid in enumerate(selected):
            view = knowledge(trial, aid)
            received = spoken["perceptions"][aid]
            decision, receipt = decide(context.workspace_path, context.operation_id + (".npc" if index == 0 else f".npc{index}"), NPCDecision, NPC,
                {"observation": view, "player_words": received["text"], "received": received}, client=client)
            actions = [action.intent() for action in decision.actions]
            validate_plan(view, actions)
            response = {"actor": aid, "speech": decision.speech, "actions": actions, "reason": decision.reason,
                        "promise": decision.promise, "duration": decision.horizon_ticks, "decision": receipt,
                        "join_party": decision.join_party, "leave_party": decision.leave_party}
            responses.append(response)
            if decision.speech:
                apply_action(trial, aid, {"kind": "speak", "target": PLAYER, "text": decision.speech,
                                          "channel": intent.get("channel", "speech")})
        simulation = Simulation(world)
        command = {"kind": "dialogue", "request": intent, "responses": responses}
        if interpreted:
            command = {**interpreted, "action": command}
        result = simulation.command(command, context.operation_id, expected_revision=revision)
        record_result(world, simulation.world, command, context.operation_id, result)
        store.save(simulation.world)
    return publish_world(context, simulation.world, result)


def interpret(context, *, client=None):
    """One DM decision and at most two recipient-limited NPC handoffs."""
    from .world_runtime import PLAYER_ACTIONS, publish_world

    store = WorldStore(context.workspace_path)
    public_request = context.payload.get("intent", {"kind": "ask", "text": context.payload.get("text", "")})
    require(isinstance(public_request.get("text"), str) and 0 < len(public_request["text"].strip()) <= 4000,
            "Describe your intent in 1 to 4000 characters.")
    with store.locked():
        world = store.read()
        previous = world["receipts"].get(context.operation_id)
        if previous:
            require(previous["intent"] == fingerprint(public_request), "That operation ID belongs to another request.")
            update = publish_world(context, world, deepcopy(previous["result"]))
            return update, describe_result(update["result"])
        require(context.payload.get("expected_revision", world["revision"]) == world["revision"],
                "The world has changed. Observe it again before acting.")
        decision, receipt = decide(context.workspace_path, context.operation_id + ".interpret", Interpretation,
                                   INTERPRETER, {"observation": knowledge(world, PLAYER),
                                                 "adjudication": dm_context(world),
                                                 "player_request": public_request["text"]}, client=client)
    intent = ({"kind": "talk", "target": decision.target, "text": decision.text, "channel": decision.channel or "speech"}
              if decision.mode == "dialogue" else decision.action.intent() if decision.mode == "action" and decision.action else None)
    require(intent is None or intent["kind"] in PLAYER_ACTIONS - {"ask", "resume", "cancel"}, "That proposed action is not supported.")
    command = {"kind": "interpreted", "request": public_request, "action": intent,
               "interpretation": {"intent": intent, "decision": receipt, "text": decision.text, "mode": decision.mode}}
    if decision.mode == "tools":
        try:
            operations = json.loads(decision.operations_json or "null")
        except (ValueError, TypeError) as error:
            raise ActionError("The DM proposal was not valid structured content. Nothing changed.") from error
        require(isinstance(operations, list) and 0 < len(operations) <= 4, "The DM can use up to four installed operations.")
        command["action"] = {"kind": "dm_tools", "operations": operations}
    if intent and intent["kind"] == "talk":
        update = converse(context, intent, world["revision"], client=client, interpreted=command,
                          handoffs=decision.handoffs or ([intent["target"]] if intent["target"] else []))
    else:
        result, after = store.execute(command, context.operation_id, expected_revision=world["revision"])
        update = publish_world(context, after, result)
    return update, describe_result(update["result"])


def combat_decision(context, revision, *, client=None):
    """One active NPC decision per request; world time is frozen during inference."""
    from .world_runtime import publish_world
    from .simulation.combat import incapacitated
    store = WorldStore(context.workspace_path)
    with store.locked():
        world = store.read()
        public = context.payload["intent"]
        previous = world["receipts"].get(context.operation_id)
        if previous:
            require(previous["intent"] == fingerprint(public), "That operation ID belongs to another request.")
            return publish_world(context, world, deepcopy(previous["result"]))
        require(world["revision"] == revision and world["combat"], "Observe the current encounter before continuing.")
        pending = world["combat"].get("pending")
        aid = pending["reactor"] if pending else world["combat"]["awaiting"]
        require(aid != PLAYER, "Your character has the next decision.")
        view = knowledge(world, aid)
        if incapacitated(world, aid) or next(entry for entry in world["combat"]["participants"] if entry["id"] == aid).get("withdrawn"):
            actions, receipt = [{"kind": "end_turn"}], {"source": "incapacitated_or_withdrawn"}
        else:
            decision, receipt = decide(context.workspace_path, context.operation_id + ".combat", CombatDecision, COMBAT,
                                       {"observation": view}, client=client)
            actions = [action.intent() for action in decision.actions]
        if pending:
            require(len(actions) == 1 and actions[0]["kind"] == "reaction", "The NPC must resolve the offered reaction.")
            action = {**actions[0], "kind": "npc_reaction", "actor": aid,
                      "mind_revision": world["actors"][aid]["mind_revision"], "decision": receipt}
        else:
            action = {"kind": "npc_turn", "actor": aid, "actions": actions,
                      "mind_revision": world["actors"][aid]["mind_revision"], "decision": receipt}
        simulation = Simulation(world)
        command = {"kind": "interpreted", "request": public, "action": action,
                   "interpretation": {"text": "The next participant decides.", "intent": public, "decision": receipt}}
        try:
            result = simulation.command(command, context.operation_id, expected_revision=revision)
            simulation.world["actors"][aid].pop("decision_feedback", None)
        except ActionError as error:
            # The failed plan is rolled back. Its owner receives the rejection
            # on their next explicitly requested decision, without another call
            # here, lost dice, or an invented fallback turn.
            simulation.world = deepcopy(world)
            simulation.world["actors"][aid]["decision_feedback"] = {
                "error": str(error), "attempted_actions": actions, "tick": world["tick"],
                "note": "None of this rejected plan was committed. Choose a legal revised plan."}
            simulation.world["revision"] += 1
            simulation.world["decisions"].append({"actor": aid, "kind": "combat_rejected", "encounter": world["combat"]["id"],
                                                "receipt": receipt, "error": str(error)})
            result = {"reason": "rejected", "message": str(error), "operation_id": context.operation_id,
                      "tick": world["tick"], "revision": simulation.world["revision"], "elapsed_ticks": 0, "elapsed_seconds": 0, "events": []}
            simulation.world["receipts"][context.operation_id] = {"intent": fingerprint(public), "result": deepcopy(result)}
        record_result(world, simulation.world, command, context.operation_id, result)
        store.save(simulation.world)
    return publish_world(context, simulation.world, result)


def describe_result(result):
    if result["reason"] == "rejected":
        return result["message"]
    interpretation = result.get("interpretation", {})
    intent = interpretation.get("intent") or {}
    if result["reason"] == "answer":
        return interpretation.get("text", "")
    lines = [e["text"] for e in result.get("events", []) if e["kind"] not in {"move", "inspect"}]
    elapsed = result.get("elapsed_seconds", 0)
    if intent.get("kind") == "travel":
        lines.append("You arrive at your destination." if result["reason"] == "arrived" else "Your journey pauses.")
    if intent.get("kind") in {"wait", "travel"}:
        lines.append(f"{elapsed} seconds pass. {result['reason'].replace('_', ' ').capitalize()}.")
    return "\n\n".join(lines[-8:]) or interpretation.get("text", "The action resolves.")


def handle_message(context):
    from RealmEngine.modules import ModuleActionContext
    from .runtime import _publish_turn_started, _publish_turn_completed, _publish_turn_failed
    from .world_runtime import execute_world_action

    turn = begin_turn(session_uuid=context.session_uuid, workspace_path=context.workspace_path,
                      player_message=context.player_message, player_message_id=context.message_id)
    _publish_turn_started(context, turn)
    action_context = ModuleActionContext(**{field: getattr(context, field) for field in (
        "module_id", "session_uuid", "realm_id", "archive_user_id", "realm_session_id", "workspace_root",
        "workspace_path", "logger")}, operation_id=f"chat-{context.message_id}", payload={
            "intent": {"kind": "ask", "text": context.player_message},
            "expected_revision": WorldStore(context.workspace_path).read()["revision"],
        })
    try:
        update = execute_world_action(action_context)
        reply = describe_result(update["result"])
        turn.turn_file_path.write_text("---\nplayer_intent: " + json.dumps(context.player_message) + "\n---\n\n" + reply + "\n")
        turn.emit_visible(speaker="DM", body=reply)
        networking.send_message(context, label="DM", body=reply,
                                payload={"world_revision": update["world"]["revision"], "world_tick": update["world"]["tick"]})
        if update["result"]["reason"] == "rejected":
            _publish_turn_failed(context, turn, reply)
        else:
            _publish_turn_completed(context, turn)
    except ActionError as error:
        # Failed adjudication consumes no time and remains reviewable in chat.
        turn.turn_file_path.write_text("---\nplayer_intent: " + json.dumps(context.player_message) + "\n---\n\n" + str(error) + "\n")
        turn.emit_visible(speaker="DM", body=str(error))
        networking.send_message(context, label="DM", body=str(error))
        _publish_turn_failed(context, turn, str(error))
