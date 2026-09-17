"""Player-facing history, committed with action receipts; never NPC knowledge."""

from copy import deepcopy

from .simulation.perception import observe
from .simulation.state import PLAYER, STEP_SECONDS


def public_intent(intent):
    return intent["request"] if intent.get("kind") in {"interpreted", "dialogue"} else intent


def duration_text(seconds):
    parts = []
    for unit, size in (("hour", 3600), ("minute", 60), ("second", 1)):
        amount, seconds = divmod(seconds, size)
        if amount:
            parts.append(f"{amount} {unit}{'s' if amount != 1 else ''}")
    return ", ".join(parts) or "0 seconds"


def describe_intent(world, intent):
    view = observe(world, PLAYER)
    known = {key: value["name"] for key, value in view["self"]["known"].items()}
    known.update({entity["id"]: entity["name"] for entity in view["actors"] + view["items"]})
    known.update({key: value["name"] for key, value in view["doors"].items()})
    known.update({key: value["name"] for key, value in world["map"]["places"].items()})
    target = known.get(intent.get("target"), "that target")
    kind = intent.get("kind")
    if kind == "ask":
        return intent.get("text", "")
    if kind == "ability":
        name = world["definitions"].get(intent.get("ability"), {}).get("name", "that ability")
        return f"Use {name}."
    if kind == "choose_class":
        return f"Take a level in {str(intent.get('class', '')).title()}."
    if kind in {"end_turn", "continue_combat", "short_rest", "long_rest", "dodge", "dash", "disengage", "retreat", "reaction", "offer_truce", "resolve_events"}:
        return {"end_turn": "End my turn.", "continue_combat": "Let the next participant decide.", "short_rest": "Take a short rest.", "long_rest": "Take a long rest.", "reaction": "Resolve the reaction."}.get(kind, kind.replace('_', ' ').capitalize() + ".")
    if kind in {"recruit", "dismiss", "order"}:
        return f"{kind.capitalize()} {target}" + (f": {intent.get('text', '')}" if kind == "order" else ".")
    if kind in {"talk", "speak"}:
        return f'Say to {target}: “{intent.get("text", "")}”'
    if kind in {"move", "travel"}:
        position = intent.get("position")
        destination = f"({position[0]}, {position[1]})" if isinstance(position, list) and len(position) == 2 else target
        return f"{'Step' if kind == 'move' else 'Travel'} to {destination}."
    if kind == "give":
        return f"Give {target} to {known.get(intent.get('recipient'), 'that person')}."
    if kind == "check":
        return f"Make a {str(intent.get('stat', 'wis')).upper()} check about {target}."
    if kind == "wait":
        activity = {"rest": "Rest", "work": "Work"}.get(intent.get("activity"), "Wait")
        ticks = intent.get("ticks", 100)
        duration = duration_text(ticks * STEP_SECONDS) if type(ticks) is int and ticks >= 0 else "the requested duration"
        duration = (f"until {intent['until_hour']:02d}:00" if type(intent.get("until_hour")) is int
                    else f"for {duration}")
        condition = intent.get("until")
        if isinstance(condition, dict):
            watched = known.get(condition.get("target"), "the target")
            trigger = {"item_taken": f"{watched} is picked up", "actor_arrived": f"{watched} arrives",
                       "actor_departed": f"{watched} leaves", "event": f"{condition.get('event', 'an event')} is observed"}
            duration += f", watching until {trigger.get(condition.get('kind'), 'the condition is met')}"
        return f"{activity} {duration}."
    if kind in {"resume", "cancel"}:
        return "Continue the saved activity." if kind == "resume" else "Pause the activity."
    verb = {"take": "Pick up", "drop": "Drop", "equip": "Equip", "use": "Use", "inspect": "Inspect", "attack": "Attack"}
    return f"{verb.get(kind, 'Interact with')} {target}."


def _summary(result, elapsed):
    reason = result["reason"]
    if reason == "rejected":
        return result["message"]
    if reason == "answer":
        return result.get("interpretation", {}).get("text", "")
    labels = {"yielded": "Activity in progress", "cancelled": "Activity paused", "arrived": "Destination reached",
              "timeout": "The planned time has passed", "condition_reached": "The watched condition was met",
              "combat_decision": "Your combat decision is needed", "conversation_complete": "Conversation complete",
              "action_complete": "Action resolved", "unconscious": "Your character is unconscious"}
    label = labels.get(reason, reason.replace("_", " ").capitalize())
    return f"{label}." + (f" {duration_text(elapsed * STEP_SECONDS)} passed." if elapsed else "")


def record_result(before, world, intent, operation_id, result):
    if operation_id in before["receipts"]:
        return
    request = public_intent(intent)
    chat = world.setdefault("game_chat", {"revision": 0, "turns": []})
    turn = next((entry for entry in reversed(chat["turns"])
                 if result["reason"] != "rejected" and request.get("kind") in {"resume", "cancel"}
                 and entry["id"] == request.get("wait_id")), None)
    if turn is None:
        turn = {"id": operation_id, "tick": before["tick"], "player": describe_intent(before, request), "messages": []}
        chat["turns"].append(turn)
    # Results contain only witnessed events. Do not copy plans, model traces,
    # private actor state, or arbitrary event fields into the visible history.
    events = result.get("events", [])
    if (result.get("action_event") and result["action_event"]["kind"] == "inspect"
            and not any(e["sequence"] == result["action_event"]["sequence"] for e in events)):
        events = [result["action_event"], *events]
    for event in events:
        if event["kind"] == "move" or (event["kind"] == "speech" and event["actor"] == PLAYER):
            continue
        text = event["text"]
        if event["kind"] == "check":
            text += f" Rolled {event['die']} {event['modifier']:+d} against {event['difficulty']}: {'success' if event['success'] else 'failure'}."
        speaker = event.get("speaker", world["actors"].get(event["actor"], {}).get("name", "Someone")) if event["kind"] == "speech" else "World"
        turn["messages"].append({"id": event["sequence"], "tick": event["tick"], "speaker": speaker, "text": text})
    # A continuation replaces its yield summary, retaining ordered witnessed
    # events in the same player turn, including after save/resume.
    turn.update(updated_tick=world["tick"], status="rejected" if result["reason"] == "rejected" else
                "running" if result["reason"] == "yielded" else "complete",
                summary=_summary(result, world["tick"] - turn["tick"]))
    chat["revision"] += 1


def chat_view(world):
    return deepcopy(world.get("game_chat", {"revision": 0, "turns": []}))
