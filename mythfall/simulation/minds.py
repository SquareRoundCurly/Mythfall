"""Observer-specific information. The event ledger is never an NPC's memory."""

from copy import deepcopy
import hashlib

from .state import distance


def active_effects(world, actor_id, kind=None):
    return [effect for effect in world.get("effects", {}).values()
            if effect.get("target") == actor_id and effect.get("ends_at", world["tick"] + 1) > world["tick"]
            and (kind is None or effect["kind"] == kind)]


def has_condition(world, actor_id, condition):
    if condition == "unconscious" and world["actors"][actor_id].get("life") == "unconscious":
        return True
    return any(effect.get("condition") == condition for effect in active_effects(world, actor_id, "condition"))


def sense_range(world, actor_id, sense):
    base = world["actors"][actor_id].get("senses", {}).get(sense, 12 if sense == "vision" else 8)
    return max(0, min(24, base + sum(e["amount"] for e in active_effects(world, actor_id, "sense") if e["sense"] == sense)))


def appearance(world, observer, actual):
    """Resolve an observer's belief about an entity, without changing that entity."""
    if observer == actual:
        return actual, world["actors"][actual]["name"]
    for effect in reversed(active_effects(world, observer, "identity")):
        if effect.get("subject") == actual:
            return effect.get("identity", actual), effect.get("name", "Unknown figure")
    for effect in reversed(active_effects(world, actual, "disguise")):
        return effect.get("identity", actual), effect.get("name", "Unknown figure")
    return actual, world["actors"][actual]["name"]


def reference(world, observer, actual):
    if actual not in world["actors"] or appearance(world, observer, actual)[0] == actual:
        return actual
    # Do not expose a disguised actor's slug in a model-visible action handle.
    # This is stable within an appearance, and can be resolved without mutating
    # the world during reads or revealing the reverse mapping to the model.
    identity, name = appearance(world, observer, actual)
    key = f"{observer}:{actual}:{identity}:{name}"
    return "seen." + hashlib.sha256(key.encode()).hexdigest()[:16]


def resolve_reference(world, observer, target):
    for aid in world["actors"]:
        if reference(world, observer, aid) == target:
            return aid
    return target


def can_identify(world, observer, actual):
    from .perception import can_see

    if observer == actual:
        return True
    hidden = world["actors"][actual]["rpg"].get("hidden", 0) if world["actors"][actual]["position"] in world["map"].get("concealment_tiles", []) else 0
    observer_actor = world["actors"][observer]
    from .checks import modifier, proficiency
    passive = 10 + modifier(observer_actor, "wis") + (proficiency(observer_actor) if "perception" in observer_actor["rpg"]["skills"] else 0)
    if "perception" in observer_actor["rpg"]["expertise"]:
        passive += proficiency(observer_actor)
    return (not hidden or passive >= hidden) and (can_see(world, observer, world["actors"][actual]["position"])
            and (not has_condition(world, actual, "invisible") or has_condition(world, observer, "see_invisible")))


def can_hear(world, observer, position, volume):
    from .perception import blocked

    actor = world["actors"][observer]
    if actor["hp"] <= 0 or actor["activity"] == "sleeping" or has_condition(world, observer, "deafened"):
        return False
    reach = min(sense_range(world, observer, "hearing"), volume)
    # Sound travels around corners through walkable tiles. Closed doors and
    # solid walls block this first acoustic model; no line-of-sight shortcut.
    start = tuple(actor["position"])
    frontier, visited = {start}, {start}
    obstacles = blocked(world)
    for _ in range(reach + 1):
        if tuple(position) in frontier:
            return True
        next_points = set()
        for x, y in frontier:
            for point in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if (point not in visited and point not in obstacles
                        and 0 <= point[0] < world["map"]["width"] and 0 <= point[1] < world["map"]["height"]):
                    next_points.add(point)
        visited.update(next_points)
        frontier = next_points
        if not frontier:
            return False
    return False


def perception_of(world, event, observer):
    from .perception import can_see

    actor = world["actors"][observer]
    source = event["actor"]
    position = event.get("position")
    channel = event.get("channel", "speech" if event["kind"] == "speech" else "sight")
    identified = source in world["actors"] and can_identify(world, observer, source)
    if observer == source:
        received = True
    elif channel == "telepathy":
        received = observer in event.get("recipients", [])
    elif channel == "private":
        received = observer in event.get("recipients", [])
    elif channel in {"speech", "whisper", "sound"}:
        volume = event.get("volume", 4 if channel == "speech" else 1 if channel == "whisper" else 8)
        received = position is not None and can_hear(world, observer, position, volume)
    elif observer in event["targets"] and event["kind"] in {"damage", "heal", "attack", "effect"}:
        received = True
    else:
        received = position is not None and can_see(world, observer, position) and (source not in world["actors"] or identified)
    if not received:
        return None
    result = {key: deepcopy(event[key]) for key in ("sequence", "tick", "kind", "text")}
    known_source = identified or observer == source or channel == "telepathy"
    result.update(actor=reference(world, observer, source) if known_source else "unknown",
                  speaker=appearance(world, observer, source)[1] if known_source and source in world["actors"] else "Someone",
                  position=deepcopy(position), channel=channel, targets=[])
    for target in event["targets"]:
        if target in world["actors"]:
            if can_identify(world, observer, target) or target == observer:
                result["targets"].append(reference(world, observer, target))
        elif target in world["items"]:
            from .perception import item_position
            point = item_position(world, world["items"][target])
            if point and can_see(world, observer, point):
                result["targets"].append(target)
        else:
            result["targets"].append(target)
    if channel in {"speech", "whisper", "telepathy"}:
        if event.get("language", "common") not in actor.get("languages", ["common"]):
            result["text"] = "Speech in an unfamiliar language."
            result["understood"] = False
        else:
            result["understood"] = True
    elif not known_source:
        result["text"] = ("A sound comes from nearby." if channel == "sound" else
                          "You are affected." if observer in event["targets"] else "Something moves nearby.")
        if observer in event["targets"]:
            result.update({key: event[key] for key in ("damage", "hp") if key in event})
    else:
        # Existing event text contains canonical names. Apply the observer's
        # appearances before the text can enter memory or an agent context.
        for aid, other in world["actors"].items():
            perceived = appearance(world, observer, aid)[1] if aid == observer or can_identify(world, observer, aid) else "someone"
            # Written testimony is intentionally allowed to mention absent people.
            if event["kind"] != "read":
                result["text"] = result["text"].replace(other["name"], perceived)
        hidden_targets = any(target in world["actors"] and target != observer and not can_identify(world, observer, target) for target in event["targets"])
        for key in ("die", "rolls", "modifier", "difficulty", "success", "hit", "damage", "hp", "armor", "skill", "total", "dice", "advantage"):
            if key in event:
                if hidden_targets and key in {"hit", "damage", "hp", "armor"}:
                    continue
                result[key] = deepcopy(event[key])
    return result


def record_perceptions(world, event):
    event["perceptions"] = {}
    for aid, actor in sorted(world["actors"].items()):
        view = perception_of(world, event, aid)
        if view is None:
            continue
        event["perceptions"][aid] = view
        if event["kind"] in {"move", "inspect", "work"}:
            continue
        memory = {**deepcopy(view), "source": "testimony" if event["kind"] in {"speech", "read"} else "observed", "confidence": "reported" if event["kind"] in {"speech", "read"} else "certain"}
        actor["memories"].append(memory)
        del actor["memories"][:-256]
        if event["kind"] in {"speech", "sound"} and aid != event["actor"]:
            actor.setdefault("attention", []).append({"sequence": event["sequence"], "kind": event["kind"],
                                                       "position": deepcopy(event["position"]), "expires_at": world["tick"] + 30})
            del actor["attention"][:-12]
        for target in view["targets"]:
            if target not in world["items"]:
                continue
            item = world["items"][target]
            if event["kind"] in {"take", "drop", "give"}:
                place = deepcopy(item["place"])
                if "carrier" in place:
                    place["carrier"] = reference(world, aid, place["carrier"])
                actor["known"][target] = {"name": item["name"], "place": place, "tick": world["tick"],
                                         "source_sequence": event["sequence"]}
        for value in actor.get("values", []):
            if value["event"] == event["kind"]:
                actor.setdefault("thoughts", []).append({"id": f"{value.get('id', value.get('name', 'value'))}:{event['sequence']}",
                    "text": value.get("text", value.get("description", value.get("name", "A valued event"))), "amount": value["amount"], "ends_at": world["tick"] + value["duration"],
                    "source_sequence": event["sequence"]})
        actor["mind_revision"] = actor.get("mind_revision", 0) + 1
    event["witnesses"] = list(event["perceptions"])


def relationship_change(world, aid, subject, amount, sequence):
    actor = world["actors"][aid]
    before = actor["relationships"].get(subject, 0)
    after = max(-10, min(10, before + amount))
    actor["relationships"][subject] = after
    actor.setdefault("relationship_events", []).append({"subject": subject, "delta": after - before, "source_sequence": sequence})


def visible_event(world, event, observer):
    if event["sequence"] in world["actors"][observer].get("suppressed_events", []):
        return None
    if "perceptions" in event:
        return deepcopy(event["perceptions"].get(observer))
    if observer in event["witnesses"]:
        return {key: deepcopy(value) for key, value in event.items() if key not in {"witnesses", "operation_id"}}
    return None


def mood(world, actor):
    needs = -max(0, actor["hunger"] - 5000) // 500 - max(0, actor["fatigue"] - 6000) // 500
    company = sum(max(-3, min(3, actor["relationships"].get(aid, 0))) for aid in world["party"]["members"] if aid != actor["id"]) if actor["id"] in world["party"]["members"] else 0
    return max(-100, min(100, needs + company + sum(t["amount"] for t in actor.get("thoughts", []) if t["ends_at"] > world["tick"])))


def private_sheet(world, aid):
    actor = world["actors"][aid]
    result = deepcopy(actor)
    for key in ("references", "suppressed_events", "relationship_events"):
        result.pop(key, None)
    result["mood"] = mood(world, actor)
    result["thoughts"] = [t for t in result.get("thoughts", []) if t["ends_at"] > world["tick"]]
    result["conditions"] = [e["condition"] for e in active_effects(world, aid, "condition")]
    # A reference map belongs to the resolver. Other actors' identities in the
    # self view must follow the same appearance mapping as visible entities.
    result["known"] = {reference(world, aid, key): {**value, "name": appearance(world, aid, key)[1]}
                       if key in world["actors"] else value for key, value in result["known"].items()}
    result["relationships"] = {reference(world, aid, key): actor["relationships"].get(appearance(world, aid, key)[0], 0)
                               if key in world["actors"] else value for key, value in result["relationships"].items()}
    if result["rpg"].get("command"):
        source = result["rpg"]["command"]["source"]
        result["rpg"]["command"]["source"] = reference(world, aid, source) if can_identify(world, aid, source) else "unknown"
    def references(value):
        if isinstance(value, str):
            return reference(world, aid, value) if value in world["actors"] else value
        if isinstance(value, list):
            return [references(entry) for entry in value]
        if isinstance(value, dict):
            return {references(key): references(entry) for key, entry in value.items()}
        return value
    for field in ("beliefs", "orders", "plan", "decision_feedback"):
        if field in result:
            result[field] = references(result[field])
    return result
