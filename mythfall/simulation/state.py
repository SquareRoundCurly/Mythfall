"""Serializable state, deterministic checks, and world invariants."""

from copy import deepcopy
import hashlib
import json

STEP_SECONDS = 6
TICKS_PER_HOUR = 3600 // STEP_SECONDS
TICKS_PER_DAY = 24 * TICKS_PER_HOUR
MAX_WAIT_TICKS = TICKS_PER_DAY
MAX_PLAN_STEPS = 12
PLAYER = "char.player"


class ActionError(ValueError):
    """A rejected intent; the caller may propose another action."""


def require(condition, message):
    if not condition:
        raise ActionError(message)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def distance(first, second):
    return abs(first[0] - second[0]) + abs(first[1] - second[1])


def roll(world, sides):
    # Persisted integer PRNG, independent of Python's process seed and wall time.
    world["rng"] = (1664525 * world["rng"] + 1013904223) & 0xFFFFFFFF
    return 1 + ((world["rng"] * sides) >> 32)


def emit(world, kind, actor, *, targets=(), text="", **details):
    from .minds import record_perceptions

    actor_state = world["actors"].get(actor)
    position = details.pop("position", None)
    if position is None and actor_state:
        position = actor_state["position"][:]
    world["sequence"] += 1
    event = {"sequence": world["sequence"], "tick": world["tick"], "kind": kind,
             "actor": actor, "targets": list(targets), "position": position,
             "witnesses": [], "text": text,
             "operation_id": world.get("_operation"), **deepcopy(details)}
    if "_cause" in world:
        event["cause"] = world["_cause"]
    world["events"].append(event)
    record_perceptions(world, event)
    from .schedules import enqueue_event
    enqueue_event(world, event)
    return event


def validate_world(world):
    require(world.get("version") == 2, "Unsupported world version.")
    require(isinstance(world.get("tick"), int) and world["tick"] >= 0, "Invalid world clock.")
    require(isinstance(world.get("rng"), int), "Missing random state.")
    require(PLAYER in world["actors"], "The player is missing.")
    require(isinstance(world.get("effects"), dict) and isinstance(world.get("schedules"), dict), "Missing effect/schedule state.")
    require(isinstance(world.get("consequences"), list) and len(world["consequences"]) <= 4096, "Invalid pending consequences.")
    party = world.get("party", {})
    require(isinstance(party.get("members"), list) and len(party["members"]) <= party.get("limit", 4)
            and len(set(party["members"])) == len(party["members"])
            and PLAYER in party["members"] and all(aid in world["actors"] for aid in party["members"]), "Invalid party members.")
    if world["combat"]:
        combat = world["combat"]
        require(1 <= len(combat.get("participants", [])) <= 8 and 0 <= combat["turn"] < len(combat["participants"]), "Invalid encounter participants.")
        require(combat["awaiting"] == combat["participants"][combat["turn"]]["id"], "Encounter turn ownership is inconsistent.")
        require({entry["id"] for entry in combat["participants"]} == set(combat["economy"]), "Encounter budgets are inconsistent.")
        for aid, budget in combat["economy"].items():
            require(aid in world["actors"] and all(type(budget.get(key)) is int and budget[key] >= 0 for key in ("action", "bonus", "reaction", "movement", "interaction")), "Invalid encounter resource budget.")
    for aid, actor in world["actors"].items():
        require(actor["id"] == aid, "Actor identity mismatch.")
        x, y = actor["position"]
        require(0 <= x < world["map"]["width"] and 0 <= y < world["map"]["height"], "Actor outside the map.")
        require(0 <= actor["hp"] <= actor["max_hp"], "Invalid health.")
        require(actor.get("life") in {"alive", "unconscious", "dead"}, "Invalid life state.")
        require(len(actor["rpg"]["classes"]) <= 3 and all(name in {"fighter", "rogue", "cleric", "wizard"} for name in actor["rpg"]["classes"]), "Invalid class progression.")
        for value in actor["rpg"]["resources"].values():
            require(type(value["current"]) is int and type(value["max"]) is int and 0 <= value["current"] <= value["max"], "Invalid character resource pool.")
        require(0 <= actor["hunger"] <= 10000 and 0 <= actor["fatigue"] <= 10000, "Invalid needs.")
        equipped = actor.get("equipped")
        if equipped:
            require(equipped in world["items"] and world["items"][equipped]["place"] == {"carrier": aid},
                    "Equipped item is not carried by its actor.")
        for slot in ("armor", "shield", "offhand"):
            iid = actor["rpg"].get(slot)
            require(not iid or iid in world["items"] and world["items"][iid]["place"] == {"carrier": aid}, "An equipped item is not carried by its actor.")
    for iid, item in world["items"].items():
        require(item["id"] == iid, "Item identity mismatch.")
        place = item["place"]
        require(isinstance(place, dict) and len(place) == 1, "An item must have exactly one location.")
        if "carrier" in place:
            require(place["carrier"] in world["actors"], "Missing item carrier.")
        elif "ground" in place:
            x, y = place["ground"]
            require(0 <= x < world["map"]["width"] and 0 <= y < world["map"]["height"], "Item outside map.")
        elif "container" in place:
            require(place["container"] in world["fixtures"], "Missing item container.")
        else:
            require(place.get("consumed") is True, "Unknown item location.")
    return world
