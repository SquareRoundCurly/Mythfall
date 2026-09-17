"""Persisted game-time and event jobs, with bounded work and causal receipts."""

from copy import deepcopy

from .checks import integer
from .effects import apply_effect, validate_effect
from .migration import allocate_id
from .state import ActionError, distance, require


MAX_JOBS = 64
MAX_REACTIONS = 64


def install_schedule(world, definition):
    require(isinstance(definition, dict), "A schedule must be an object.")
    allowed = {"name", "source", "actor", "trigger", "effects", "actions", "conditions", "remaining", "cooldown"}
    require(set(definition) <= allowed, "Unknown schedule field.")
    require(sum(job["remaining"] > 0 for job in world["schedules"].values()) < MAX_JOBS, "This world has reached its active schedule limit.")
    source = definition.get("source")
    require(source in world["actors"] or source in world["fixtures"] or source in world["zones"], "A schedule needs an existing source.")
    name = definition.get("name", "Scheduled work")
    require(isinstance(name, str) and 0 < len(name) <= 120, "Invalid schedule name.")
    trigger = definition.get("trigger", {})
    require(isinstance(trigger, dict) and trigger.get("kind") in {"time", "interval", "event", "enter"}, "Unknown schedule trigger.")
    kind = trigger["kind"]
    allowed_trigger = {"kind", "at"} if kind == "time" else {"kind", "every", "at"} if kind == "interval" else {"kind", "event", "actor", "target", "position", "radius"}
    require(set(trigger) <= allowed_trigger, "Unknown trigger field.")
    trigger = deepcopy(trigger)
    if kind in {"time", "interval"}:
        if kind == "interval":
            integer(trigger.get("every"), 1, 14400 * 30, "schedule interval")
        trigger["at"] = trigger.get("at", world["tick"] + trigger.get("every", 1))
        integer(trigger["at"], world["tick"], world["tick"] + 14400 * 365, "scheduled time")
    else:
        require(kind == "enter" or isinstance(trigger.get("event"), str) and 0 < len(trigger["event"]) <= 40, "An event trigger needs an event kind.")
        if kind == "enter" or "position" in trigger:
            point = trigger.get("position")
            require(isinstance(point, list) and len(point) == 2 and all(type(v) is int for v in point), "A spatial trigger needs a position.")
            require(0 <= point[0] < world["map"]["width"] and 0 <= point[1] < world["map"]["height"], "Trigger is outside the map.")
            integer(trigger.get("radius", 0), 0, 12, "trigger radius")
    effects = definition.get("effects", [])
    actions = definition.get("actions", [])
    require(isinstance(effects, list) and len(effects) <= 8, "A schedule permits at most eight effects.")
    require(isinstance(actions, list) and len(actions) <= 12, "A schedule permits at most twelve actions.")
    require(bool(effects) != bool(actions), "Choose scheduled effects or an actor plan.")
    for effect in effects:
        validate_effect(effect)
    if actions:
        from .routines import install_plan
        trial = deepcopy(world)
        install_plan(trial, definition.get("actor"), actions, name, source="schedule")
    conditions = definition.get("conditions", [])
    require(isinstance(conditions, list) and len(conditions) <= 8, "At most eight schedule conditions are allowed.")
    for condition in conditions:
        validate_predicate(condition)
    remaining = definition.get("remaining", 1 if kind == "time" else 100000)
    integer(remaining, 1, 100000, "schedule repetitions")
    cooldown = integer(definition.get("cooldown", 1), 1, 14400, "schedule cooldown")
    sid = allocate_id(world, "schedule")
    world["schedules"][sid] = {**deepcopy(definition), "id": sid, "name": name, "trigger": trigger,
                              "effects": effects, "actions": actions, "conditions": conditions,
                              "remaining": remaining, "cooldown": cooldown, "ready_at": world["tick"],
                              "created_at": world["tick"], "last_event": world["sequence"], "failures": []}
    return sid


def validate_predicate(condition):
    require(isinstance(condition, dict) and condition.get("kind") in {"need", "life", "condition", "diet"}, "Unknown schedule condition.")
    kind = condition["kind"]
    allowed = {"kind", "actor", "need", "gte"} if kind == "need" else {"kind", "actor", "value"}
    require(set(condition) <= allowed and isinstance(condition.get("actor"), str), "Invalid schedule condition fields.")
    if kind == "need":
        require(condition.get("need") in {"hunger", "fatigue"}, "Unknown scheduled need.")
        integer(condition.get("gte"), 0, 10000, "need threshold")
    elif kind == "life":
        require(condition.get("value") in {"alive", "unconscious", "dead"}, "Unknown life state.")
    else:
        require(isinstance(condition.get("value"), str) and 0 < len(condition["value"]) <= 60, "Invalid condition value.")


def bind(value, job):
    return {"$actor": job.get("event", {}).get("actor"), "$source": job["source"],
            "$target": next(iter(job.get("event", {}).get("targets", [])), None)}.get(value, value)


def predicate(world, condition, job):
    from .minds import has_condition

    aid = bind(condition["actor"], job)
    actor = world["actors"].get(aid)
    if actor is None:
        return False
    kind = condition["kind"]
    if kind == "need":
        return actor[condition["need"]] >= condition["gte"]
    if kind == "life":
        return actor["life"] == condition["value"]
    if kind == "condition":
        return has_condition(world, aid, condition["value"])
    return condition["value"] in actor["diet"]


def _queue(world, schedule, event=None):
    if schedule["remaining"] <= 0 or schedule["ready_at"] > world["tick"]:
        return
    job = {"schedule": schedule["id"], "source": schedule["source"],
           "event": {key: deepcopy(event[key]) for key in ("sequence", "actor", "targets", "position")} if event else {},
           "operation_id": world.get("_operation")}
    if not all(predicate(world, condition, job) for condition in schedule["conditions"]):
        return
    job["id"] = allocate_id(world, "consequence")
    schedule["remaining"] -= 1
    schedule["ready_at"] = world["tick"] + schedule["cooldown"]
    world["consequences"].append(job)


def enqueue_event(world, event):
    for schedule in sorted(world.get("schedules", {}).values(), key=lambda value: value["id"]):
        trigger = schedule["trigger"]
        if trigger["kind"] not in {"event", "enter"} or event["sequence"] <= schedule["last_event"]:
            continue
        matches = event["kind"] == ("move" if trigger["kind"] == "enter" else trigger["event"])
        matches &= "actor" not in trigger or event["actor"] == trigger["actor"]
        matches &= "target" not in trigger or trigger["target"] in event["targets"]
        if "position" in trigger:
            matches &= event.get("position") is not None and distance(event["position"], trigger["position"]) <= trigger.get("radius", 0)
        if matches:
            schedule["last_event"] = event["sequence"]
            _queue(world, schedule, event)


def enqueue_time(world):
    for schedule in sorted(world["schedules"].values(), key=lambda value: value["id"]):
        trigger = schedule["trigger"]
        if trigger["kind"] in {"time", "interval"} and schedule["remaining"] and trigger["at"] <= world["tick"]:
            _queue(world, schedule)
            if trigger["kind"] == "interval":
                trigger["at"] += trigger["every"]
            else:
                schedule["remaining"] = 0


def drain(world, limit=MAX_REACTIONS):
    """Commit each reaction once. Failed jobs leave no partial effect changes."""
    integer(limit, 1, MAX_REACTIONS, "reaction work budget")
    if world.get("_draining"):
        return len(world["consequences"])
    world["_draining"] = True
    processed = 0
    while world["consequences"] and processed < limit:
        job = world["consequences"].pop(0)
        before = deepcopy(world)
        schedule = world["schedules"].get(job["schedule"])
        if schedule is None:
            processed += 1
            continue
        old_cause = world.get("_cause")
        world["_cause"] = job["event"].get("sequence", job["id"])
        try:
            if all(predicate(world, condition, job) for condition in schedule["conditions"]):
                if schedule["actions"]:
                    from .routines import install_plan
                    install_plan(world, schedule["actor"], schedule["actions"], schedule["name"], source="schedule")
                for effect in schedule["effects"]:
                    bound = deepcopy(effect)
                    for key in ("target", "subject", "identity"):
                        if key in bound:
                            bound[key] = bind(bound[key], job)
                    target = bound.get("target", schedule["source"])
                    apply_effect(world, schedule["source"], target, bound)
        except ActionError as error:
            world.clear()
            world.update(before)
            failures = world["schedules"][job["schedule"]]["failures"]
            failures.append({"job": job["id"], "tick": world["tick"], "reason": str(error)})
            del failures[:-16]
        finally:
            if old_cause is None:
                world.pop("_cause", None)
            else:
                world["_cause"] = old_cause
        processed += 1
    world.pop("_draining", None)
    return len(world["consequences"])
