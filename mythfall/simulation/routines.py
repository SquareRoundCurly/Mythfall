"""Local routine execution and bounded, interruptible NPC plans."""

from copy import deepcopy

from .actions import inventory
from .perception import can_see, path_to, walkable
from .state import ActionError, MAX_PLAN_STEPS, PLAYER, TICKS_PER_HOUR, distance, emit, require
from .minds import can_identify, resolve_reference


def install_plan(world, aid, actions, reason, *, source="model", duration=600):
    require(aid in world["actors"] and aid != PLAYER, "Choose an NPC.")
    require(isinstance(actions, list) and 0 < len(actions) <= MAX_PLAN_STEPS, "A plan needs 1 to 12 actions.")
    require(isinstance(reason, str) and 0 < len(reason) <= 800, "A plan needs a short reason.")
    require(isinstance(duration, int) and 1 <= duration <= 14400, "Invalid plan horizon.")
    for action in actions:
        require(isinstance(action, dict) and action.get("kind") in {
            "travel", "take", "drop", "give", "equip", "unequip", "use", "speak", "rest", "work", "idle", "inspect", "check", "attack",
            "ability", "traverse", "read", "write", "put", "eat_remains"
        }, "Invalid plan action.")
        require(len(str(action)) <= 1800, "Plan action is too large.")
    plan = {"actions": deepcopy(actions), "reason": reason, "source": source,
            "created_at": world["tick"], "expires_at": world["tick"] + duration}
    world["actors"][aid]["plan"] = plan
    world["actors"][aid]["ready_at"] = world["tick"]
    if source == "model":
        world["decisions"].append({"actor": aid, "tick": world["tick"], "plan": deepcopy(plan)})


def _travel(world, actor, target, *, adjacent=False):
    if actor["position"] == target or (adjacent and distance(actor["position"], target) <= 1):
        return None
    path = path_to(world, actor["position"], target, adjacent=adjacent)
    if not path:
        raise ActionError("The planned destination is blocked.")
    return {"kind": "move", "position": path[0]}


def planned_action(world, aid):
    actor = world["actors"][aid]
    plan = actor["plan"]
    if plan is None:
        return None
    if plan["expires_at"] <= world["tick"]:
        actor["plan"] = None
        return None
    while plan["actions"]:
        action = plan["actions"][0]
        if action["kind"] == "travel":
            target = action.get("position")
            observed_target = resolve_reference(world, aid, action.get("target"))
            if observed_target in world["actors"]:
                other = world["actors"][observed_target]
                target = (other["position"] if can_identify(world, aid, observed_target)
                          else actor["known"].get(observed_target, {}).get("position"))
            elif action.get("target") in world["items"]:
                item = world["items"][action["target"]]
                if "ground" not in item["place"]:
                    raise ActionError("The planned ground item is no longer there.")
                point = item["place"]["ground"]
                target = point if can_see(world, aid, point) else actor["known"].get(item["id"], {}).get("position")
            elif action.get("target") in world["map"]["places"]:
                target = world["map"]["places"][action["target"]]["center"]
            elif action.get("target") in world["fixtures"]:
                fixture = world["fixtures"][action["target"]]
                from .perception import item_position
                point = item_position(world, world["items"][fixture["item"]]) if fixture.get("item") else fixture["position"]
                target = point if point is not None and can_see(world, aid, point) else actor["known"].get(action["target"], {}).get("position")
            require(isinstance(target, list) and len(target) == 2
                    and all(isinstance(v, int) for v in target) and walkable(world, target), "Invalid plan destination.")
            movement = _travel(world, actor, target, adjacent=action.get("adjacent", False))
            if movement:
                return movement
            plan["actions"].pop(0)
        else:
            return plan["actions"].pop(0)
    actor["plan"] = None
    return None


def choose_action(world, aid):
    actor = world["actors"][aid]
    planned = planned_action(world, aid)
    if planned:
        return planned
    if actor["hunger"] >= min(9000, 6500 + actor.get("duty", 0) * 20):
        food = next((i for i in inventory(world, aid) if i["kind"] == "food"), None)
        if food:
            return {"kind": "use", "target": food["id"]}
        food_action = seek_food(world, aid)
        if food_action:
            return food_action

    if aid in world["party"]["members"]:
        leader = world["actors"][world["party"]["leader"]]
        if can_identify(world, aid, leader["id"]) and distance(actor["position"], leader["position"]) > 1:
            return _travel(world, actor, leader["position"], adjacent=True) or {"kind": "idle"}
        if not can_identify(world, aid, leader["id"]):
            journey = actor.get("journey", {})
            destination = journey.get("destination") if journey.get("expires_at", 0) > world["tick"] else actor["known"].get(leader["id"], {}).get("position")
            if destination:
                return _travel(world, actor, destination, adjacent=True) or {"kind": "idle"}
        return {"kind": "idle"}

    hour = (world["tick"] // TICKS_PER_HOUR) % 24
    if hour >= 22 or hour < 6 or actor["fatigue"] >= 9000 or (actor["activity"] == "sleeping" and actor["fatigue"] > 3000):
        return _travel(world, actor, actor["home"]) or {"kind": "rest"}

    if actor.get("duty", 0) < 50:
        sounds = [event for event in actor.get("attention", []) if event["kind"] == "sound" and event["expires_at"] > world["tick"]]
        if sounds:
            heard = sounds[-1]
            actor["attention"] = [event for event in actor["attention"] if event["sequence"] != heard["sequence"]]
            install_plan(world, aid, [{"kind": "travel", "position": heard["position"]}, {"kind": "idle"}],
                         "Investigate a sound heard nearby.", source="routine", duration=30)
            return planned_action(world, aid) or {"kind": "idle"}

    # Finding lost property is a generic perception/motive rule for any item.
    from .objects import load, item_load
    carried_weight = load(world, aid)
    for iid, item in sorted(world["items"].items()):
        position = item["place"].get("ground")
        if position is None or not can_see(world, aid, position) or actor["interest"] == "none":
            continue
        if actor["interest"] == "study" and item["kind"] not in {"book", "trinket"}:
            continue
        if carried_weight + item_load(world, item) > actor["capacity"]:
            continue
        if actor["considered"].get(iid, {}).get("until", 0) > world["tick"]:
            continue
        if path_to(world, actor["position"], position, adjacent=True) is None:
            actor["considered"][iid] = {"until": world["tick"] + 50}
            continue
        actor["known"][iid] = {"position": position[:], "tick": world["tick"], "name": item["name"]}
        install_plan(world, aid, [{"kind": "travel", "target": iid, "adjacent": True}, {"kind": "take", "target": iid}],
                     f"{actor['interest']}: noticed {item['name']} on the ground.", source="routine", duration=100)
        emit(world, "notice", aid, targets=[iid], text=f"{actor['name']} notices {item['name']}.")
        return planned_action(world, aid)

    return _travel(world, actor, actor["work"]) or {"kind": "work"}


def seek_food(world, aid):
    """Search observed supplies or remembered opportunities, never hidden stock."""
    actor = world["actors"][aid]
    if "remains" in actor["diet"]:
        bodies = [(distance(actor["position"], other["position"]), other_id, other["position"]) for other_id, other in world["actors"].items()
                  if other["life"] == "dead" and other.get("remains") and not other["remains"]["consumed"] and can_see(world, aid, other["position"])]
        if bodies:
            _, target, point = min(bodies)
            return _travel(world, actor, point, adjacent=True) or {"kind": "eat_remains", "target": target}
    candidates = []
    for iid, item in world["items"].items():
        if item["kind"] not in actor.get("diet", ["food"]):
            continue
        point = item["place"].get("ground")
        container = world["fixtures"].get(item["place"].get("container"))
        if container and container.get("open") and distance(actor["position"], container["position"]) <= 1:
            point = container["position"]
        if point and can_see(world, aid, point):
            candidates.append((distance(actor["position"], point), iid, point))
    if candidates:
        _, iid, point = min(candidates)
        return _travel(world, actor, point, adjacent=True) or {"kind": "take", "target": iid}
    opportunities = {fid: fixture for fid, fixture in world["fixtures"].items()
                     if can_see(world, aid, fixture["position"])}
    opportunities.update({fid: memory for fid, memory in actor["known"].items()
                          if fid in world["fixtures"] and fid not in opportunities})
    for fid, known in sorted(opportunities.items(), key=lambda pair: (distance(actor["position"], pair[1].get("position", actor["position"])), pair[0])):
        if not set(actor.get("diet", ["food"])) & set(known.get("offers", [])):
            continue
        if actor["considered"].get("supply:" + fid, {}).get("until", 0) > world["tick"]:
            continue
        point = known["position"]
        if distance(actor["position"], point) <= 1:
            actor["considered"]["supply:" + fid] = {"until": world["tick"] + 100}
            continue
        return _travel(world, actor, point, adjacent=True)
    return None
