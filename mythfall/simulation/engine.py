"""The single world clock and transactional, resumable command boundary."""

from copy import deepcopy
import re

from .actions import apply_action
from .conditions import condition_reached, validate_condition
from .perception import can_see, observe, path_to, walkable, geometry_scope
from .routines import choose_action, install_plan
from .migration import upgrade_world
from .minds import can_identify, visible_event, resolve_reference, reference
from .effects import expire_effects
from .schedules import drain, enqueue_time
from .state import (
    ActionError, MAX_WAIT_TICKS, PLAYER, STEP_SECONDS, TICKS_PER_DAY, TICKS_PER_HOUR,
    distance, emit, fingerprint, require, validate_world,
)

MAX_CHUNK_TICKS = 300


class Simulation:
    def __init__(self, world):
        self.world = validate_world(upgrade_world(world))

    @geometry_scope
    def command(self, intent, operation_id, *, expected_revision=None, chunk_ticks=MAX_CHUNK_TICKS):
        require(isinstance(operation_id, str) and re.fullmatch(r"[A-Za-z0-9._:-]{1,120}", operation_id),
                "A stable operation ID is required.")
        require(isinstance(intent, dict), "An intent must be an object.")
        require(isinstance(chunk_ticks, int) and 1 <= chunk_ticks <= MAX_CHUNK_TICKS, "Invalid advancement chunk.")
        # Trusted dialogue carries its public request for effect-safe retries.
        digest = fingerprint(intent["request"] if intent.get("kind") in {"dialogue", "interpreted"} else intent)
        previous = self.world["receipts"].get(operation_id)
        if previous:
            require(previous["intent"] == digest, "That operation ID belongs to a different intent.")
            return deepcopy(previous["result"])
        require(expected_revision is None or expected_revision == self.world["revision"],
                "The world has changed. Observe it again before acting.")
        original = self.world
        self.world = deepcopy(original)
        self.world["_operation"] = operation_id
        start, sequence = self.world["tick"], self.world["sequence"]
        try:
            result = self._command(deepcopy(intent), operation_id, chunk_ticks)
            drain(self.world)
            from .adventure import evaluate
            evaluate(self.world)
            self.world.pop("_operation", None)
            validate_world(self.world)
            self.world["revision"] += 1
            result.update(tick=self.world["tick"], elapsed_ticks=self.world["tick"] - start,
                          elapsed_seconds=(self.world["tick"] - start) * STEP_SECONDS,
                          revision=self.world["revision"], operation_id=operation_id,
                          events=[view for e in self.world["events"] if e["sequence"] > sequence
                                  if (view := visible_event(self.world, e, PLAYER)) is not None])
            if result.get("action_event"):
                result["action_event"] = visible_event(self.world, result["action_event"], PLAYER)
            self.world["receipts"][operation_id] = {"intent": digest, "result": deepcopy(result)}
            return result
        except Exception:
            self.world = original
            raise

    def _command(self, intent, operation_id, chunk_ticks):
        world = self.world
        kind = intent.get("kind")
        from . import combat
        if kind == "dm_tools":
            from .authoring import author, ruling
            operations = intent.get("operations", [])
            require(isinstance(operations, list) and 0 < len(operations) <= 4, "At most four DM operations per decision.")
            for operation in operations:
                if operation.get("kind") == "ruling":
                    ruling(world, PLAYER, operation.get("ruling"))
                    drain(world)
                    if not world["combat"]:
                        self._step()
                else:
                    author(world, operation)
            return {"reason": "ruling_complete"}
        if kind == "npc_turn":
            aid = intent.get("actor")
            require(world["combat"] and aid != PLAYER and world["combat"]["awaiting"] == aid, "That NPC is not awaiting a combat turn.")
            actions = intent.get("actions", [])
            require(isinstance(actions, list) and 0 < len(actions) <= 12, "A combat decision needs 1–12 actions.")
            require(intent.get("mind_revision") == world["actors"][aid]["mind_revision"], "That NPC decision is stale.")
            world["decisions"].append({"actor": aid, "tick": world["tick"], "encounter": world["combat"]["id"],
                                       "turn": world["combat"]["turn_serial"], "actions": deepcopy(actions), "receipt": intent.get("decision")})
            for action in actions:
                require(action.get("kind") in {"move", "attack", "offhand", "ability", "use", "equip", "unequip", "speak", "dodge", "dash", "disengage", "hide", "stand", "help", "end_turn", "retreat", "offer_truce"}, "That combat action is unsupported.")
                self._actor_action(aid, action)
                if not world["combat"] or world["combat"]["awaiting"] != aid or world["combat"]["pending"]:
                    break
            return {"reason": "combat_decision" if world["combat"] else "action_complete"}
        if kind == "npc_reaction":
            aid = intent.get("actor")
            require(aid != PLAYER and intent.get("mind_revision") == world["actors"][aid]["mind_revision"], "That reaction is stale.")
            event = combat.reaction(world, aid, intent)
            world["decisions"].append({"actor": aid, "tick": world["tick"], "reaction": deepcopy(intent)})
            return {"reason": "combat_decision", "action_event": event}
        if kind == "resolve_events":
            remaining = drain(world)
            return {"reason": "consequences_pending" if remaining else "action_complete"}
        require(not world["consequences"], "Resolve the pending consequences before another action.")
        if kind in {"resume", "cancel"}:
            require(world["pending"] is not None and world["pending"]["status"] == "running", "No advancement is waiting to continue.")
            require(intent.get("wait_id") == world["pending"]["id"], "That wait is no longer current.")
            return self._finish("cancelled") if kind == "cancel" else self._advance(chunk_ticks)
        require(world["pending"] is None or world["pending"]["status"] != "running", "Cancel or finish the current activity first.")
        require(world["actors"][PLAYER]["hp"] > 0 or kind in {"end_turn", "reaction", "interpreted"}
                or kind == "wait" and world["actors"][PLAYER]["life"] == "unconscious", "Your character is unconscious.")
        if kind == "npc_plan":
            install_plan(world, intent.get("actor"), intent.get("actions"), intent.get("reason"),
                         duration=intent.get("duration", 600))
            return {"reason": "plan_accepted"}
        if kind == "interpreted":
            if intent.get("action"):
                result = self._command(intent["action"], operation_id, chunk_ticks)
            else:
                result = {"reason": "answer"}
            result["interpretation"] = deepcopy(intent["interpretation"])
            return result
        if kind == "dialogue":
            request = intent["request"]
            require(world["combat"] is None, "Resolve the encounter before starting a conversation.")
            _, spoken = apply_action(world, PLAYER, {**request, "kind": "speak"})
            responses = intent.get("responses", [{**intent, "actor": request.get("target")}])
            require(len(responses) <= 2, "A conversation supports two handoffs.")
            for response in responses:
                aid = response["actor"]
                require(aid in spoken["perceptions"] and aid != PLAYER, "That NPC did not receive the communication.")
                if response.get("speech"):
                    apply_action(world, aid, {"kind": "speak", "target": PLAYER, "text": response["speech"], "channel": request.get("channel", "speech")})
                if response.get("promise"):
                    emit(world, "promise", aid, targets=[PLAYER], text=response["promise"], status="stated_intention", channel=request.get("channel", "speech"))
                if response.get("actions"):
                    install_plan(world, aid, response["actions"], response["reason"], duration=response["duration"])
                if response.get("join_party"):
                    world["actors"][aid]["join_offer_until"] = world["tick"] + 100
                    emit(world, "party_offer", aid, targets=[PLAYER], text=f"{world['actors'][aid]['name']} is willing to join your party.")
                if response.get("leave_party") and aid in world["party"]["members"]:
                    world["party"]["members"].remove(aid)
                    world["actors"][aid]["orders"] = None
                    emit(world, "party_leave", aid, text=f"{world['actors'][aid]['name']} leaves the party.")
                world["decisions"].append({"actor": aid, "kind": "handoff", "source_event": spoken["sequence"], "receipt": response.get("decision")})
            self._step()
            return {"reason": "conversation_complete", "speakers": [reference(world, PLAYER, response["actor"]) for response in responses]}
        if kind in {"wait", "travel", "short_rest", "long_rest", "copy_spell"}:
            require(world["combat"] is None, "Choose a combat action before waiting or travelling.")
            pending = {"id": operation_id, "kind": kind, "status": "running", "start_tick": world["tick"],
                       "start_sequence": world["sequence"], "activity": intent.get("activity", "watch"),
                       "until": deepcopy(intent.get("until"))}
            require(pending["activity"] in {"watch", "rest", "work"}, "Choose watch, rest, or work.")
            if kind == "travel":
                target = intent.get("position")
                if intent.get("target"):
                    from .perception import known_destination
                    target = known_destination(world, PLAYER, intent["target"])
                require(isinstance(target, list) and len(target) == 2 and all(isinstance(v, int) and not isinstance(v, bool) for v in target)
                        and walkable(world, target), "Choose a reachable map destination.")
                path = path_to(world, world["actors"][PLAYER]["position"], target, adjacent=bool(intent.get("adjacent")))
                require(path is not None, "No route reaches that destination.")
                pending.update(route=path, destination=target, end_tick=world["tick"] + len(path), activity="travel")
                if len(world["party"]["members"]) > 1:
                    language = world["actors"][PLAYER]["languages"][0]
                    announced = emit(world, "travel_plan", PLAYER, text=f"The party sets a destination at {target[0]}, {target[1]}.", channel="speech", language=language)
                    for aid in world["party"]["members"]:
                        if aid != PLAYER and aid in announced["perceptions"] and language in world["actors"][aid]["languages"]:
                            world["actors"][aid]["journey"] = {"destination": target[:], "shared_at": world["tick"], "expires_at": world["tick"] + 600, "source_sequence": announced["sequence"]}
                            world["actors"][aid]["ready_at"] = world["tick"]
            else:
                ticks = 600 if kind == "short_rest" else 4800 if kind == "long_rest" else intent.get("ticks", 10 * TICKS_PER_HOUR // 60)
                if kind == "copy_spell":
                    from .characters import copy_spell
                    ticks = copy_spell(world, PLAYER, intent)
                    pending.update(activity="work", copy_intent=deepcopy(intent))
                if kind in {"short_rest", "long_rest"}:
                    members = [aid for aid in world["party"]["members"] if world["actors"][aid]["hp"] > 0
                               and distance(world["actors"][aid]["position"], world["actors"][PLAYER]["position"]) <= 4]
                    pending.update(activity="rest", rest_intent=deepcopy(intent), rest_members=members)
                    if kind == "long_rest":
                        require(world["tick"] + ticks - world["actors"][PLAYER]["rpg"].get("long_rest_at", -14400) >= 14400, "Only one long rest per day can restore resources.")
                if "until_hour" in intent:
                    hour = intent["until_hour"]
                    require(isinstance(hour, int) and not isinstance(hour, bool) and 0 <= hour < 24, "World hour must be 0 to 23.")
                    ticks = (hour * TICKS_PER_HOUR - world["tick"]) % TICKS_PER_DAY
                require(isinstance(ticks, int) and not isinstance(ticks, bool) and 0 <= ticks <= MAX_WAIT_TICKS,
                        "A wait must be between zero and one simulated day.")
                validate_condition(world, pending["until"])
                pending["end_tick"] = world["tick"] + ticks
            world["pending"] = pending
            return self._advance(chunk_ticks)

        return self._actor_action(PLAYER, intent)

    def _actor_action(self, aid, intent):
        from . import combat
        world = self.world
        kind = intent.get("kind")
        combat.validate_compulsion(world, aid, intent)
        if kind == "offer_truce":
            require(world["combat"] is not None, "There is no fight to settle.")
            combat.pay(world, aid, "free")
            entry = next(entry for entry in world["combat"]["participants"] if entry["id"] == aid)
            entry["peace_offer"] = True
            emit(world, "truce_offer", aid, text=f"{world['actors'][aid]['name']} offers to stop fighting.", channel="speech", language=world["actors"][aid]["languages"][0])
            if combat.finish_if_resolved(world):
                return {"reason": "action_complete"}
            return self._actor_action(aid, {"kind": "end_turn"})
        if (world["combat"] and kind == "move" and isinstance(intent.get("position"), list) and len(intent["position"]) == 2 and all(type(n) is int for n in intent["position"])
                and distance(world["actors"][aid]["position"], intent["position"]) > 1):
            path = path_to(world, world["actors"][aid]["position"], intent["position"])
            require(path is not None and len(path) <= combat.turn_budget(world, aid)["movement"], "No route fits the remaining movement.")
            result = {"reason": "combat_decision"}
            for point in path:
                result = self._actor_action(aid, {"kind": "move", "position": point})
                if not world["combat"] or world["combat"]["pending"] or world["actors"][aid]["hp"] <= 0:
                    break
            return result
        if kind == "end_turn":
            require(world["combat"] and world["combat"]["awaiting"] == aid, "It is not your turn.")
            wrapped = combat.end_turn(world)
            if wrapped:
                self._step()
            if not combat.finish_if_resolved(world):
                combat.begin_turn(world)
            return {"reason": "combat_decision" if world["combat"] else "action_complete"}
        if kind == "reaction":
            event = combat.reaction(world, aid, intent)
            combat.finish_if_resolved(world)
            return {"reason": "combat_decision" if world["combat"] else "action_complete", "action_event": event}
        if kind == "retreat":
            require(world["combat"] and world["combat"]["awaiting"] == aid, "Retreat during your turn.")
            require(all(distance(world["actors"][aid]["position"], world["actors"][entry["id"]]["position"]) > 6
                        or not can_identify(world, entry["id"], aid) for entry in world["combat"]["participants"]
                        if entry["side"] != combat.side(world, aid) and world["actors"][entry["id"]]["hp"] > 0), "Break sight or gain distance from your enemies before leaving the encounter.")
            for entry in world["combat"]["participants"]:
                if entry["id"] == aid:
                    entry["withdrawn"] = True
            emit(world, "retreat", aid, text=f"{world['actors'][aid]['name']} withdraws from the encounter.")
            if combat.finish_if_resolved(world):
                return {"reason": "action_complete"}
            return self._actor_action(aid, {"kind": "end_turn"})
        if world["combat"]:
            require(kind in {"attack", "offhand", "move", "climb", "use", "equip", "unequip", "inspect", "speak", "check", "ability", "dodge", "dash", "disengage", "hide", "stand", "help", "take", "drop", "give", "order"}, "That action is unavailable during an encounter.")
        cost, event = apply_action(world, aid, intent)
        drain(world)
        if not world["combat"]:
            world["actors"][aid]["ready_at"] = world["tick"] + cost
            for _ in range(cost):
                self._step()
                if world["combat"]:
                    break
        else:
            combat.finish_if_resolved(world)
        return {"reason": "combat_decision" if world["combat"] else "action_complete", "action_event": deepcopy(event)}

    def _advance(self, chunk_ticks):
        world, pending = self.world, self.world["pending"]
        if world["combat"]:
            return self._finish("combat_decision")
        if condition_reached(world, pending):
            return self._finish("condition_reached")
        count = 0
        while world["tick"] < pending["end_tick"] and count < chunk_ticks:
            if pending["kind"] == "travel":
                if not pending["route"]:
                    return self._finish("arrived")
                if not walkable(world, pending["route"][0]):
                    return self._finish("blocked")
                apply_action(world, PLAYER, {"kind": "move", "position": pending["route"].pop(0)})
            else:
                world["actors"][PLAYER]["activity"] = {"rest": "sleeping", "watch": "watching", "work": "working"}[pending["activity"]]
            before = world["sequence"]
            self._step()
            count += 1
            if world["actors"][PLAYER]["life"] == "dead" or world["actors"][PLAYER]["hp"] <= 0 and world["combat"]:
                return self._finish("unconscious")
            if world["combat"]:
                return self._finish("combat_decision")
            if condition_reached(world, pending):
                return self._finish("condition_reached")
            for event in reversed(world["events"]):
                if event["sequence"] <= before:
                    break
                if PLAYER in event["witnesses"] and event["kind"] in {"attack", "damage", "death", "speech", "needs_attention"}:
                    return self._finish("interrupted")
        if world["tick"] >= pending["end_tick"]:
            return self._finish("arrived" if pending["kind"] == "travel" else "timeout" if pending["until"] else "duration_elapsed")
        return {"reason": "yielded", "wait_id": pending["id"], "remaining_ticks": pending["end_tick"] - world["tick"]}

    def _finish(self, reason):
        pending = self.world["pending"]
        pending["status"] = reason
        pending["stopped_at"] = self.world["tick"]
        self.world["actors"][PLAYER]["activity"] = "idle"
        if pending["kind"] in {"short_rest", "long_rest"}:
            for aid in pending["rest_members"]:
                actor = self.world["actors"][aid]
                if actor["hp"] > 0 and actor["activity"] == "sleeping":
                    actor["activity"] = "idle"
        if reason == "duration_elapsed" and pending["kind"] == "copy_spell":
            from .characters import copy_spell
            copy_spell(self.world, PLAYER, pending["copy_intent"], commit=True)
        if reason == "duration_elapsed" and pending["kind"] in {"short_rest", "long_rest"}:
            from .characters import finish_rest
            for aid in pending["rest_members"]:
                actor = self.world["actors"][aid]
                if actor["life"] != "dead" and actor["rpg"].get("last_damage_at", -1) < pending["start_tick"]:
                    if pending["kind"] == "long_rest" and self.world["tick"] - actor["rpg"].get("long_rest_at", -14400) < 14400:
                        continue
                    finish_rest(self.world, aid, "short" if pending["kind"] == "short_rest" else "long",
                                pending["rest_intent"] if aid == PLAYER else {})
        return {"reason": reason, "wait_id": pending["id"],
                "total_elapsed_ticks": self.world["tick"] - pending["start_tick"]}

    def _step(self):
        world = self.world
        world["tick"] += 1
        from .objects import tick_objects
        tick_objects(world)
        expire_effects(world)
        enqueue_time(world)
        drain(world)
        for aid in sorted(world["actors"]):
            actor = world["actors"][aid]
            if actor["life"] == "unconscious" and aid in world["party"]["members"] and not (world["combat"] and aid in world["combat"]["economy"]):
                from .minds import has_condition
                if not has_condition(world, aid, "stable"):
                    from .combat import death_save
                    death_save(world, aid)
            if actor["hp"] <= 0:
                continue
            actor["hunger"] = min(10000, actor["hunger"] + 1)
            actor["fatigue"] = max(0, min(10000, actor["fatigue"] + (-3 if actor["activity"] == "sleeping" else 1)))
            if aid == PLAYER and actor["hunger"] >= 9000 and not actor["needs_warning"]:
                actor["needs_warning"] = True
                emit(world, "needs_attention", aid, text="You are very hungry. Find something to eat.")
            if aid == PLAYER or actor["ready_at"] > world["tick"]:
                continue
            if world["combat"] and aid in world["combat"]["economy"]:
                continue
            if world["pending"] and world["pending"]["status"] == "running" and world["pending"]["kind"] in {"short_rest", "long_rest"} and aid in world["pending"]["rest_members"]:
                actor["activity"] = "sleeping"
                continue
            try:
                intent = choose_action(world, aid)
                cost, _ = apply_action(world, aid, intent)
                drain(world)
                following = aid in world["party"]["members"] and (world.get("pending") or {}).get("kind") == "travel" and world["pending"]["status"] == "running"
                world["actors"][aid]["ready_at"] = world["tick"] + (1 if following else max(1, cost))
            except ActionError as error:
                actor = world["actors"][aid]
                actor["plan"] = None
                actor["activity"] = "idle"
                actor["ready_at"] = world["tick"] + 10
                emit(world, "plan_blocked", aid, text=f"{actor['name']} changes plans.", cause=str(error))
        self._perceive()

    def _perceive(self):
        from .minds import sense_range, has_condition
        for aid, actor in self.world["actors"].items():
            if actor["hp"] <= 0 or actor["activity"] == "sleeping" or has_condition(self.world, aid, "blinded"):
                continue
            radius = sense_range(self.world, aid, "vision")
            for other_id, other in self.world["actors"].items():
                if other_id != aid and distance(actor["position"], other["position"]) <= radius and can_identify(self.world, aid, other_id):
                    actor["known"][other_id] = {"name": other["name"], "position": other["position"][:], "tick": self.world["tick"]}
            for fid, fixture in self.world["fixtures"].items():
                from .perception import item_position
                point = item_position(self.world, self.world["items"][fixture["item"]]) if fixture.get("item") else fixture["position"]
                if point is not None and distance(actor["position"], point) <= radius and can_see(self.world, aid, point):
                    actor["known"].setdefault(fid, {}).update(name=fixture["name"], position=point[:],
                                            offers=fixture.get("offers", []), tick=self.world["tick"])

    def observe(self, actor_id=PLAYER):
        return observe(self.world, actor_id)
