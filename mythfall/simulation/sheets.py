"""Read-only game panels; never serialize another actor's private mind."""

from copy import deepcopy

from .catalog import CLASSES, XP_THRESHOLDS, item_rules
from .characters import armor_class, casting_unavailable, prepared_abilities, speed, spells_for
from .combat import incapacitated
from .minds import active_effects, appearance, mood, reference
from .state import PLAYER


def unavailable(world, aid, spec):
    actor = world["actors"][aid]
    if incapacitated(world, aid):
        return "Incapacitated"
    if spec.get("resource") and actor["rpg"]["resources"].get(spec["resource"], {}).get("current", 0) <= 0:
        return "No uses remaining; recover with the appropriate rest"
    if spec.get("level") and not any(value["current"] for key, value in actor["rpg"]["resources"].items() if key.startswith("slot_") and int(key[-1]) >= spec["level"]):
        return "No suitable spell slots remaining"
    if spec.get("spell"):
        reason = casting_unavailable(world, aid, spec)
        if reason:
            return reason
    if spec["economy"] == "rest" and actor["rpg"].get("short_rest_at", -1) != world["tick"]:
        return "Available when a short rest finishes"
    combat = world["combat"]
    if combat:
        if spec["economy"] == "reaction":
            if not combat.get("pending") or combat["pending"]["reactor"] != aid:
                return "Requires a reaction trigger"
        elif combat["awaiting"] != aid or combat.get("pending"):
            return "Wait for this character's turn"
        if spec["economy"] not in {"free", "rest"} and combat["economy"].get(aid, {}).get(spec["economy"], 0) <= 0:
            return "No " + spec["economy"] + " remaining"
    elif spec["economy"] == "reaction":
        return "Requires a reaction trigger"
    return None


def character_sheet(world, aid):
    actor = world["actors"][aid]
    rpg = actor["rpg"]
    data = {key: deepcopy(actor[key]) for key in ("name", "position", "color", "hp", "max_hp", "stats", "life", "activity", "equipped", "hunger", "fatigue")}
    data.update(id=reference(world, PLAYER, aid), name=appearance(world, PLAYER, aid)[1])
    data["rpg"] = {key: deepcopy(rpg.get(key)) for key in ("classes", "level", "subclasses", "skills", "expertise", "saves", "features", "xp", "resources", "armor", "shield", "offhand", "attuned", "style", "prepared_by_class", "cantrips", "spellbook")}
    data.update(armor_class=armor_class(world, aid), speed=speed(world, aid), mood=mood(world, actor),
                relationship=actor["relationships"].get(PLAYER, 0) if aid != PLAYER else None)
    data["effects"] = [{"id": effect["id"], "kind": effect["kind"], "label": effect.get("condition", effect["kind"]),
                        "remaining_ticks": effect["ends_at"] - world["tick"]} for effect in active_effects(world, aid)]
    data["abilities"] = [{**deepcopy(world["definitions"][key]), "unavailable": unavailable(world, aid, world["definitions"][key])}
                         for key in prepared_abilities(world, aid)]
    data["inventory"] = [{**deepcopy(item), "rules": deepcopy(item_rules(world, item))} for item in world["items"].values() if item["place"].get("carrier") == aid]
    for item in data["inventory"]:
        if item.get("message") and aid != PLAYER:
            item["message"] = {"sealed": item["message"]["sealed"]}
    data["prepare_options"] = {name: spells_for(world, name, rpg["classes"].count(name)) for name in set(rpg["classes"]) & {"cleric", "wizard"}}
    if "wizard" in data["prepare_options"]:
        data["prepare_options"]["wizard"] = [key for key in data["prepare_options"]["wizard"] if key in rpg.get("spellbook", [])]
    level = len(rpg["classes"])
    data["next_level_xp"] = XP_THRESHOLDS[level] if level < 3 else None
    data["can_level"] = level < 3 and rpg["xp"] >= XP_THRESHOLDS[level] and not world["combat"]
    return data


def party_sheets(world):
    return {reference(world, PLAYER, aid): character_sheet(world, aid) for aid in world["party"]["members"]}
