"""Typed shared effects used by abilities, rulings, objects, and schedules."""

from copy import deepcopy

from .checks import dice, integer, validate_dice
from .migration import allocate_id
from .state import distance, emit, require


CONDITIONS = frozenset({"blinded", "deafened", "invisible", "see_invisible", "poisoned", "frightened",
    "charmed", "restrained", "prone", "incapacitated", "stunned", "paralyzed", "unconscious",
    "stable", "guarded", "disengaged", "sanctuary", "shielded", "telepathy", "mage_armor", "detect_magic", "turned", "commanded", "silenced"})
FIELDS = {
    "damage": {"dice", "amount", "damage_type", "nonlethal"}, "heal": {"dice", "amount"},
    "condition": {"condition", "duration"}, "remove_condition": {"condition"},
    "need": {"need", "amount"}, "thought": {"text", "amount", "duration"},
    "memory": {"sequences", "text"}, "belief": {"subject", "text", "confidence"},
    "identity": {"subject", "identity", "name", "duration"},
    "disguise": {"identity", "name", "duration"},
    "check_bonus": {"dice", "stat", "saving", "attack", "once", "duration"},
    "move": {"position", "teleport", "distance"}, "sound": {"volume", "position"},
    "door": {"open", "locked"}, "relationship": {"subject", "amount"},
    "sense": {"sense", "amount", "duration"},
    "max_hp": {"amount", "duration"}, "resource": {"resource", "amount"},
    "object_damage": {"amount", "dice"}, "link": {"open"},
}
REQUIRED = {
    "condition": {"condition", "duration"}, "remove_condition": {"condition"},
    "need": {"need", "amount"}, "thought": {"text", "amount", "duration"},
    "memory": {"sequences", "text"}, "belief": {"subject", "text"},
    "identity": {"subject", "identity", "name", "duration"},
    "disguise": {"identity", "name", "duration"}, "check_bonus": {"dice", "duration"},
    "move": {"position"}, "sound": {"volume"}, "relationship": {"subject", "amount"},
    "sense": {"sense", "amount", "duration"},
    "max_hp": {"amount", "duration"}, "resource": {"resource", "amount"},
    "link": {"open"},
}


def validate_effect(effect):
    require(isinstance(effect, dict) and effect.get("kind") in FIELDS, "Unknown effect operation.")
    kind = effect["kind"]
    require(set(effect) <= FIELDS[kind] | {"kind", "target"}, "Unknown effect field.")
    require(REQUIRED.get(kind, set()) <= set(effect), "Missing effect fields.")
    if "target" in effect:
        require(isinstance(effect["target"], str) and 0 < len(effect["target"]) <= 120, "Invalid effect target.")
    if "duration" in effect:
        integer(effect["duration"], 1, 14400 * 7, "effect duration")
    if "amount" in effect:
        bounds = (-10000, 10000) if kind == "need" else (-20, 20) if kind in {"thought", "sense"} else (-10, 10) if kind == "relationship" else (-200, 200) if kind == "resource" else (0, 200)
        integer(effect["amount"], *bounds, "effect amount")
    if kind in {"damage", "heal", "object_damage"}:
        require(("dice" in effect) != ("amount" in effect), "Choose a damage/healing amount or dice.")
    if "dice" in effect:
        validate_dice(effect["dice"])
    if "condition" in effect:
        require(effect["condition"] in CONDITIONS, "Unsupported condition.")
    if "text" in effect:
        require(isinstance(effect["text"], str) and len(effect["text"]) <= 800, "Effect text is too long.")
    if "name" in effect:
        require(isinstance(effect["name"], str) and 0 < len(effect["name"]) <= 100, "Invalid perceived name.")
    if "sequences" in effect:
        require(isinstance(effect["sequences"], list) and len(effect["sequences"]) <= 16
                and all(type(n) is int and n > 0 for n in effect["sequences"]), "Choose up to 16 memory events.")
    if "position" in effect:
        require(isinstance(effect["position"], list) and len(effect["position"]) == 2
                and all(type(n) is int for n in effect["position"]), "Invalid effect position.")
    for flag in ("nonlethal", "saving", "attack", "once", "teleport", "open", "locked"):
        require(flag not in effect or type(effect[flag]) is bool, f"Invalid {flag} flag.")
    if kind == "door":
        require("open" in effect or "locked" in effect, "A door effect must change its state.")
    if "stat" in effect:
        from .checks import STATS
        require(effect["stat"] in STATS, "Invalid effect stat.")
    if "need" in effect:
        require(effect["need"] in {"hunger", "fatigue"}, "Unknown need.")
    if "sense" in effect:
        require(effect["sense"] in {"vision", "hearing"}, "Unknown sense.")
    if "volume" in effect:
        integer(effect["volume"], 1, 24, "sound volume")
    if "distance" in effect:
        integer(effect["distance"], 0, 12, "movement range")
    for field in ("subject", "identity"):
        require(field not in effect or isinstance(effect[field], str) and 0 < len(effect[field]) <= 120,
                f"Invalid effect {field}.")
    if "confidence" in effect:
        require(effect["confidence"] in {"certain", "suspected", "reported"}, "Invalid belief confidence.")
    if "damage_type" in effect:
        require(effect["damage_type"] in {"bludgeoning", "piercing", "slashing", "fire", "cold", "lightning",
            "thunder", "acid", "poison", "psychic", "radiant", "necrotic", "force"}, "Unknown damage type.")
    if "resource" in effect:
        require(isinstance(effect["resource"], str) and len(effect["resource"]) <= 80, "Invalid resource reference.")
    return deepcopy(effect)


def invalidate_mind(actor):
    actor["mind_revision"] += 1
    actor["plan"] = None
    actor["attention"] = []


def damage(world, source, target, amount, *, damage_type="bludgeoning", nonlethal=False, critical=False):
    actor = world["actors"][target]
    before = actor["hp"]
    actor["hp"] = max(0, before - amount)
    actor["plan"] = None
    event = emit(world, "damage", source, targets=[target], text=f"{actor['name']} takes {amount} {damage_type} damage.",
                 damage=amount, hp=actor["hp"], damage_type=damage_type, position=actor["position"])
    if amount == 0:
        return event
    for eid, effect in list(world["effects"].items()):
        if effect["target"] == target and effect.get("condition") == "stable":
            remove_effect(world, eid)
    actor["rpg"]["last_damage_at"] = world["tick"]
    for eid, effect in list(world["effects"].items()):
        if effect["target"] == target and effect.get("condition") == "turned" and amount:
            remove_effect(world, eid)
    if actor["rpg"].get("concentration") and amount:
        from .checks import check
        saved = check(world, target, stat="con", difficulty=max(10, amount // 2), saving=True)
        emit(world, "check", target, text=f"{actor['name']} checks concentration.", **saved)
        if not saved["success"] or actor["hp"] == 0:
            end_concentration(world, target)
    if actor["hp"] == 0:
        member = target in world["party"]["members"]
        if member and before == 0 and amount:
            actor["rpg"]["death_saves"]["failure"] += 2 if critical else 1
        dead = (not member and not nonlethal) or (member and amount >= before + actor["max_hp"])
        dead |= actor["rpg"]["death_saves"]["failure"] >= 3
        actor["life"] = "dead" if dead else "unconscious"
        actor["activity"] = actor["life"]
        if dead:
            actor.setdefault("remains", {"nutrition": 5000, "consumed": False})
        if before > 0 or dead:
            emit(world, "death" if dead else "unconscious", target,
                 text=f"{actor['name']} {'dies' if dead else 'falls unconscious'}.")
    return event


def apply_effect(world, source, target, specification, *, origin=None, concentration=None, repeat_save=None, save_dc=None, breaks_on=None, critical=False):
    effect = validate_effect(specification)
    kind = effect["kind"]
    target = effect.pop("target", target)
    require(source in world["actors"] or source in world["fixtures"] or source in world.get("zones", {}), "Unknown effect source.")
    if kind == "link":
        require(target in world["links"], "Unknown connection.")
        world["links"][target]["open"] = effect["open"]
        return emit(world, "link", source, targets=[target], position=world["links"][target]["from"], text=f"{world['links'][target]['name']} {'opens' if effect['open'] else 'closes'}.")
    if kind == "object_damage":
        obj = world["fixtures"].get(target) or world["items"].get(target)
        require(obj and type(obj.get("hp")) is int and obj["hp"] > 0, "That object has no remaining destructible structure.")
        rolled = dice(world, effect["dice"]) if "dice" in effect else None
        amount = rolled["total"] if rolled else effect["amount"]
        obj["hp"] = max(0, obj["hp"] - amount)
        from .perception import item_position
        point = item_position(world, obj) if target in world["items"] else obj["position"]
        event = emit(world, "object_damage", source, targets=[target], position=point, text=f"{obj['name']} takes {amount} damage.", damage=amount, hp=obj["hp"])
        if obj["hp"] == 0:
            emit(world, "object_destroyed", source, targets=[target], position=point, text=f"{obj['name']} breaks.")
        return event
    if kind == "door":
        require(target in world["map"]["doors"], "Unknown door.")
        door = world["map"]["doors"][target]
        require(effect.get("open", True) or not any(a["position"] == door["position"] for a in world["actors"].values()),
                "Someone is standing in the doorway.")
        door.update({key: effect[key] for key in ("open", "locked") if key in effect})
        return emit(world, "door", source, targets=[target], position=door["position"], text=f"{door['name']} changes.")
    if kind == "sound":
        position = effect.get("position", world["actors"].get(target, {}).get("position"))
        require(position is not None, "A sound needs a position.")
        require(0 <= position[0] < world["map"]["width"] and 0 <= position[1] < world["map"]["height"], "Sound is outside the map.")
        return emit(world, "sound", source, position=position, volume=effect["volume"], channel="sound", text="A sound comes from nearby.")
    require(target in world["actors"], "Unknown effect recipient.")
    actor = world["actors"][target]
    require(actor["life"] != "dead", "That creature is dead.")
    if kind in {"damage", "heal"}:
        rolled = dice(world, effect["dice"]) if "dice" in effect else None
        amount = rolled["total"] if rolled else effect["amount"]
        if kind == "damage":
            event = damage(world, source, target, amount, damage_type=effect.get("damage_type", "bludgeoning"),
                           nonlethal=effect.get("nonlethal", False), critical=critical)
        else:
            before = actor["hp"]
            actor["hp"] = min(actor["max_hp"], actor["hp"] + amount)
            if actor["hp"]:
                actor.update(life="alive", activity="idle")
                actor["rpg"]["death_saves"] = {"success": 0, "failure": 0}
            event = emit(world, "heal", source, targets=[target], text=f"{actor['name']} recovers {actor['hp'] - before} health.", hp=actor["hp"])
        if rolled:
            event["dice"] = rolled
        return event
    if kind == "need":
        actor[effect["need"]] = max(0, min(10000, actor[effect["need"]] + effect["amount"]))
        invalidate_mind(actor)
    elif kind == "resource":
        require(effect["resource"] in actor["rpg"]["resources"], "Unknown resource pool.")
        pool = actor["rpg"]["resources"][effect["resource"]]
        pool["current"] = min(pool["max"], max(0, pool["current"] + effect["amount"]))
    elif kind == "thought":
        actor["thoughts"].append({"id": allocate_id(world, "thought"), "text": effect["text"], "amount": effect["amount"],
                                  "ends_at": world["tick"] + effect["duration"]})
        invalidate_mind(actor)
    elif kind == "memory":
        selected = set(effect["sequences"])
        require(selected <= {m["sequence"] for m in actor["memories"]}, "A selected memory is no longer accessible.")
        actor["suppressed_events"] = sorted(set(actor["suppressed_events"]) | selected)
        actor["memories"] = [m for m in actor["memories"] if m["sequence"] not in selected]
        actor["beliefs"] = [b for b in actor["beliefs"] if b.get("source_sequence") not in selected]
        actor["thoughts"] = [t for t in actor["thoughts"] if t.get("source_sequence") not in selected]
        actor["known"] = {key: value for key, value in actor["known"].items() if value.get("source_sequence") not in selected}
        for field in ("journey", "orders"):
            if (actor.get(field) or {}).get("source_sequence") in selected:
                actor.pop(field, None)
        for change in actor.get("relationship_events", []):
            if change["source_sequence"] in selected:
                subject = change["subject"]
                actor["relationships"][subject] = max(-10, min(10, actor["relationships"].get(subject, 0) - change["delta"]))
        actor["relationship_events"] = [change for change in actor.get("relationship_events", []) if change["source_sequence"] not in selected]
        if effect["text"]:
            actor["memories"].append({"sequence": world["sequence"] + 1, "tick": world["tick"], "kind": "recollection",
                "actor": target, "targets": [], "text": effect["text"], "source": "remembered", "confidence": "certain"})
        invalidate_mind(actor)
    elif kind == "belief":
        actor["beliefs"].append({"subject": effect["subject"], "text": effect["text"],
                                 "confidence": effect.get("confidence", "reported"), "tick": world["tick"]})
        invalidate_mind(actor)
    elif kind == "relationship":
        require(effect["subject"] in world["actors"], "Unknown relationship subject.")
        actor["relationships"][effect["subject"]] = max(-10, min(10, actor["relationships"].get(effect["subject"], 0) + effect["amount"]))
        invalidate_mind(actor)
    elif kind == "move":
        from .perception import can_see, path_to, walkable
        position = effect["position"]
        require(0 <= position[0] < world["map"]["width"] and 0 <= position[1] < world["map"]["height"] and walkable(world, position), "Movement destination is blocked.")
        limit = effect.get("distance", 6)
        require(distance(actor["position"], position) <= limit, "Movement exceeds the effect's range.")
        if effect.get("teleport"):
            require(can_see(world, target, position), "The destination is not visible.")
        else:
            route = path_to(world, actor["position"], position)
            require(route is not None and len(route) <= limit, "No route fits this movement.")
        from .schedules import drain
        for point in ([position] if effect.get("teleport") else route):
            if world["actors"][target]["hp"] <= 0:
                break
            world["actors"][target]["position"] = point[:]
            event = emit(world, "move", target, position=point, text=f"{actor['name']} moves.")
            # Reactions produced by movement resolve at each crossed cell.
            if not world.get("_draining"):
                drain(world)
        return event if 'event' in locals() else None
    elif kind == "remove_condition":
        for eid, existing in list(world["effects"].items()):
            if existing["target"] == target and existing.get("condition") == effect["condition"]:
                remove_effect(world, eid)
        invalidate_mind(actor)
    else:
        # The same named source does not stack with itself; it refreshes.
        stack_key = (origin or source, target, kind, effect.get("condition"), effect.get("stat"), effect.get("saving"), effect.get("attack"))
        for eid, existing in list(world["effects"].items()):
            if tuple(existing.get("stack_key", ())) == stack_key:
                remove_effect(world, eid)
        eid = allocate_id(world, "effect")
        world["effects"][eid] = {**effect, "id": eid, "target": target, "source": source,
                                 "starts_at": world["tick"], "ends_at": world["tick"] + effect["duration"],
                                 "origin": origin, "stack_key": list(stack_key), "concentration": concentration,
                                 "repeat_save": repeat_save, "save_dc": save_dc, "breaks_on": breaks_on}
        if kind == "max_hp":
            actor["max_hp"] += effect["amount"]
            actor["hp"] += effect["amount"]
        if kind == "condition" and effect["condition"] in {"incapacitated", "stunned", "paralyzed", "unconscious"}:
            end_concentration(world, target)
        invalidate_mind(actor)
    # Mental changes have a private mechanical record, not a public narration
    # naming the original memory or revealing the caster to the affected NPC.
    mental = kind in {"memory", "belief", "thought", "identity", "relationship", "need"}
    return emit(world, "effect", source, targets=[target], text="A change takes effect.",
                channel="private" if mental else "sight", recipients=[] if mental else [target], effect_kind=kind)


def expire_effects(world):
    expired = [eid for eid, e in world["effects"].items() if e["ends_at"] <= world["tick"]]
    for eid in expired:
        effect = world["effects"][eid]
        aid = effect["target"]
        if effect.get("condition") == "stable" and world["actors"][aid]["life"] == "unconscious":
            apply_effect(world, aid, aid, {"kind": "heal", "amount": 1})
        remove_effect(world, eid)
    for actor in world["actors"].values():
        actor["thoughts"] = [thought for thought in actor["thoughts"] if thought["ends_at"] > world["tick"]]
        actor["attention"] = [event for event in actor["attention"] if event["expires_at"] > world["tick"]]


def remove_effect(world, eid):
    effect = world["effects"].pop(eid, None)
    if not effect or effect["target"] not in world["actors"]:
        return
    actor = world["actors"][effect["target"]]
    if effect["kind"] == "max_hp":
        actor["max_hp"] = max(1, actor["max_hp"] - effect["amount"])
        actor["hp"] = max(0, min(actor["max_hp"], actor["hp"] - effect["amount"]))
        if actor["hp"] == 0 and actor["life"] != "dead":
            actor.update(life="unconscious", activity="unconscious")
            end_concentration(world, effect["target"])
    invalidate_mind(actor)


def end_concentration(world, aid):
    marker = world["actors"][aid]["rpg"].pop("concentration", None)
    if marker:
        for eid, effect in list(world["effects"].items()):
            if effect.get("concentration") == marker:
                remove_effect(world, eid)
        emit(world, "concentration_end", aid, text=f"{world['actors'][aid]['name']} stops concentrating.")


def break_effects(world, aid, trigger, *, harmful=True):
    if trigger == "attack_or_spell":
        world["actors"][aid]["rpg"].pop("hidden", None)
    for eid, effect in list(world["effects"].items()):
        if effect["target"] == aid and effect.get("breaks_on") == trigger:
            remove_effect(world, eid)
        elif trigger == "attack_or_spell" and harmful and effect["target"] == aid and effect.get("condition") == "sanctuary":
            remove_effect(world, eid)
