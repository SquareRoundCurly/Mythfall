"""Bounded player waits evaluated against that player's perception."""

from .perception import can_see
from .state import PLAYER, distance, require
from .minds import can_identify, resolve_reference


def validate_condition(world, condition):
    if condition is None:
        return
    require(isinstance(condition, dict), "Wait condition must be an object.")
    kind, target = condition.get("kind"), condition.get("target")
    player = world["actors"][PLAYER]
    if kind == "item_taken":
        require(target in world["items"], "Unknown item in wait condition.")
        item = world["items"][target]
        require(target in player["known"] or item["place"].get("carrier") == PLAYER
                or ("ground" in item["place"] and can_see(world, PLAYER, item["place"]["ground"])),
                "You have not observed that item.")
    elif kind in {"actor_arrived", "actor_departed"}:
        require(target in world["actors"] and target != PLAYER, "Choose another character.")
        require(target in player["known"] or can_identify(world, PLAYER, target),
                "You have not observed that character.")
        point = condition.get("position", player["position"])
        require(isinstance(point, list) and len(point) == 2 and point == player["position"],
                "Watch for arrivals or departures at your current position.")
        condition["position"] = point[:]
        require(condition.get("radius", 4) == 4, "The first milestone uses a four-tile arrival radius.")
    elif kind == "event":
        require(condition.get("event") in {"speech", "attack", "take", "give", "drop", "notice"}, "Unsupported observed event.")
    else:
        require(False, "Unknown wait condition.")


def condition_reached(world, pending):
    condition = pending.get("until")
    if condition is None:
        return False
    kind, target = condition["kind"], condition.get("target")
    player = world["actors"][PLAYER]
    if kind == "item_taken":
        seen = player["known"].get(target, {})
        carrier = seen.get("place", {}).get("carrier")
        return carrier is not None and carrier != PLAYER
    if kind == "actor_arrived":
        actor = world["actors"][target]
        return can_identify(world, PLAYER, target) and distance(actor["position"], condition["position"]) <= 4
    if kind == "actor_departed":
        # Departure is an observed crossing, not a query of a hidden location.
        return any(e["sequence"] > pending["start_sequence"] and e["actor"] == target
                   and e["kind"] == "move" and PLAYER in e["witnesses"]
                   and distance(e["position"], condition["position"]) > 4 for e in world["events"][-200:])
    return any(e["sequence"] > pending["start_sequence"] and e["kind"] == condition["event"]
               and PLAYER in e["witnesses"] for e in world["events"][-200:])
