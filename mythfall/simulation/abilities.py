"""Validated activation of installed and DM-authored ability definitions."""

from copy import deepcopy

from .catalog import class_level, definition, item_rules
from .characters import casting_stat, casting_unavailable, prepared_abilities, spend
from .checks import check, dice, integer, modifier, proficiency, validate_dice
from .effects import apply_effect, break_effects, end_concentration, remove_effect
from .migration import allocate_id
from .minds import can_identify, has_condition, resolve_reference
from .perception import can_see, item_position, walkable
from .state import distance, emit, require

MECHANICS = {"second_wind", "action_surge", "dash", "disengage", "hide", "turn_undead", "preserve_life",
    "arcane_recovery", "light", "magic_missile", "thunderwave", "command", "aid", "restoration",
    "spiritual_weapon", "spiritual_strike", "misty_step", "mage_hand", "fast_hands"}


def targets_for(world, aid, spec, intent):
    actor = world["actors"][aid]
    mode = spec["target"]
    point = intent.get("position")
    ids = intent.get("targets", [intent["target"]] if intent.get("target") else [])
    require(isinstance(ids, list) and len(ids) <= 12 and all(isinstance(key, str) for key in ids), "Choose a bounded target list.")
    ids = [resolve_reference(world, aid, key) for key in ids]
    require(len(ids) == len(set(ids)), "Choose each target once.")
    if mode == "self":
        ids = [aid]
    elif mode in {"point", "cone", "cube", "area"}:
        if mode == "area":
            point = actor["position"][:]
        require(isinstance(point, list) and len(point) == 2 and all(type(n) is int for n in point), "Choose a map point.")
        require(can_see(world, aid, point) and distance(actor["position"], point) <= spec["range"], "That point is out of sight or range.")
        if mode == "cone":
            dx, dy = point[0] - actor["position"][0], point[1] - actor["position"][1]
            require((dx == 0) != (dy == 0), "Aim the cone along one cardinal direction.")
            direction = [0 if dx == 0 else 1 if dx > 0 else -1, 0 if dy == 0 else 1 if dy > 0 else -1]
            def inside(position):
                px, py = position[0] - actor["position"][0], position[1] - actor["position"][1]
                forward = px * direction[0] + py * direction[1]
                return 1 <= forward <= spec["radius"] and abs(px * direction[1] - py * direction[0]) < forward
        elif mode == "cube":
            def inside(position):
                return point[0] <= position[0] < point[0] + spec["radius"] and point[1] <= position[1] < point[1] + spec["radius"]
        else:
            def inside(position):
                return distance(point, position) <= spec.get("radius", 0)
        if mode != "point":
            ids = [key for key, body in sorted(world["actors"].items()) if body["life"] != "dead" and inside(body["position"])
                   and can_see(world, aid, body["position"])]
        else:
            ids = []
    require(len(ids) <= spec["max_targets"], "Too many targets for this ability.")
    require(ids or mode in {"point", "cone", "cube", "area"}, "Choose an ability target.")
    for target in ids:
        if mode == "object":
            obj = world["items"].get(target)
            position = item_position(world, obj) if obj else world["fixtures"].get(target, {}).get("position")
            require(position is not None and can_see(world, aid, position), "Choose an observable object.")
            if obj:
                from .perception import observe
                require(target in {entry["id"] for entry in observe(world, aid)["items"]}, "That object is not observable.")
        else:
            require(target in world["actors"] and world["actors"][target]["life"] != "dead", "Choose a living creature.")
            body = world["actors"][target]
            position = body["position"]
            require(target == aid or can_identify(world, aid, target) or body["hp"] == 0 and can_see(world, aid, position)
                    or mode in {"area", "cone", "cube"}, "You cannot perceive that target.")
            require(not spec.get("species") or body["species"] == spec["species"], "That power cannot affect this kind of creature.")
        require(mode in {"cone", "cube", "area"} or distance(actor["position"], position) <= spec["range"], "An ability target is out of range.")
    return ids, point


def activate(world, aid, intent, *, item=None, paid=False):
    from .combat import attack_roll, pay, turn_budget
    actor = world["actors"][aid]
    key = intent.get("ability")
    spec = deepcopy(definition(world, key))
    require(spec["type"] == "ability", "Choose an ability definition.")
    require(item is not None or key in prepared_abilities(world, aid), "You have not learned or prepared that ability.")
    mechanic = spec.get("mechanic")
    level = spec.get("level", 0)
    slot = intent.get("slot", level)
    integer(slot, level, 2, "spell slot")
    if not level:
        require(slot == 0, "Cantrips and features do not consume spell slots.")
    if key in {"ability.bless@1", "ability.command@1"}:
        spec["max_targets"] += slot - level
    # Spiritual Weapon's position is physical state, not a free remote attack.
    if mechanic == "spiritual_strike":
        weapon = actor["rpg"].get("spiritual_weapon", {})
        require(weapon.get("ends_at", 0) > world["tick"], "No spiritual weapon remains.")
        point = intent.get("position", weapon["position"])
        require(isinstance(point, list) and len(point) == 2 and all(type(n) is int for n in point)
                and distance(point, weapon["position"]) <= 4 and walkable(world, point) and can_see(world, aid, point), "The spiritual weapon can move at most four visible tiles.")
        spec["range"] = 24
        target_id = resolve_reference(world, aid, intent.get("target"))
        require(target_id in world["actors"] and distance(world["actors"][target_id]["position"], point) <= 1, "Move the spiritual weapon within reach of its target.")
        weapon["position"] = point[:]
    targets, point = targets_for(world, aid, spec, intent)
    stat = casting_stat(actor, spec, intent.get("class"))
    if mechanic == "spiritual_strike":
        stat = actor["rpg"]["spiritual_weapon"]["stat"]
    dc = 8 + proficiency(actor) + modifier(actor, stat)
    if spec.get("spell") and item is None:
        unavailable = casting_unavailable(world, aid, spec)
        require(unavailable is None, unavailable or "Spell components are unavailable.")
        if world["combat"] and world["combat"]["awaiting"] == aid:
            budget = turn_budget(world, aid)
            if spec["economy"] == "bonus":
                require(not budget.get("cast_levelled"), "A bonus-action spell permits only action cantrips for other spells that turn.")
            elif budget.get("cast_bonus"):
                require(level == 0 and spec["economy"] == "action", "After a bonus-action spell, only an action cantrip can be cast this turn.")
    if mechanic == "command":
        command = intent.get("command")
        require(command in {"approach", "drop", "flee", "grovel", "halt"}, "Choose Approach, Drop, Flee, Grovel, or Halt.")
        require(all(world["actors"][target]["species"] != "undead" and set(actor["languages"]) & set(world["actors"][target]["languages"]) for target in targets), "Command requires a living recipient who understands your language.")
    if key == "ability.mage_armor@1":
        require(all(not world["actors"][target]["rpg"].get("armor") for target in targets), "Mage Armor requires an unarmored target.")
    if mechanic == "magic_missile":
        require(len(targets) <= 2 + slot, "Each chosen target needs at least one missile.")
    if mechanic == "restoration":
        require(intent.get("condition") in {"blinded", "deafened", "paralyzed", "poisoned"}, "Choose one supported condition to remove.")
    if mechanic == "arcane_recovery":
        require(not world["combat"] and actor["rpg"].get("short_rest_at", -1) == world["tick"], "Use Arcane Recovery at the end of a short rest.")
        slots = intent.get("slots", [1])
        require(isinstance(slots, list) and all(type(n) is int and n in (1, 2) for n in slots)
                and 0 < sum(slots) <= (class_level(actor, "wizard") + 1) // 2, "That exceeds Arcane Recovery's slot budget.")
        require(all(f"slot_{n}" in actor["rpg"]["resources"] for n in slots), "You do not have that slot level.")
    economy = "free" if spec["economy"] == "rest" else spec["economy"]
    if level and item is None:
        require(actor["rpg"]["resources"].get(f"slot_{slot}", {}).get("current", 0) > 0, "No spell slot of that level remains.")
    opening_targets = targets if spec.get("hostile") else []
    if mechanic == "spiritual_weapon" and intent.get("target"):
        target = resolve_reference(world, aid, intent["target"])
        require(target in world["actors"] and world["actors"][target]["life"] != "dead"
                and distance(world["actors"][target]["position"], point) <= 1 and can_identify(world, aid, target), "The new spiritual weapon cannot reach that target.")
        opening_targets = [target]
    if opening_targets and world["combat"] is None:
        from .combat import start
        start(world, aid, [key for key in opening_targets if key != aid])
        if world["combat"]["awaiting"] != aid:
            return emit(world, "initiative_wait", aid, text="Initiative is rolled; act when your turn arrives.")
    if not paid:
        pay(world, aid, economy)
    if spec.get("hostile") or opening_targets:
        from .combat import break_truce
        break_truce(world)
    if level and item is None:
        spend(actor, f"slot_{slot}")
    if spec.get("resource"):
        spend(actor, spec["resource"])
    if spec.get("spell") and world["combat"] and world["combat"]["awaiting"] == aid:
        budget = turn_budget(world, aid)
        budget["cast_bonus"] |= spec["economy"] == "bonus"
        budget["cast_levelled"] |= level > 0 and spec["economy"] != "bonus"
    if (spec.get("spell") or spec.get("hostile")) and spec["resolution"] != "attack" and mechanic != "spiritual_weapon":
        break_effects(world, aid, "attack_or_spell", harmful=bool(spec.get("hostile")))
    concentration = None
    if spec.get("concentration"):
        end_concentration(world, aid)
        concentration = allocate_id(world, "concentration")
        actor["rpg"]["concentration"] = concentration
    event = emit(world, "ability", aid, targets=targets, text=f"{actor['name']} uses {spec['name']}.", ability=key, slot=slot, dc=dc)
    old_cause = world.get("_cause")
    world["_cause"] = event["sequence"]
    try:
        special = resolve_special(world, aid, spec, intent, targets, point, slot, stat)
        if special:
            return event
        sculpt = intent.get("exclude", [])
        require(isinstance(sculpt, list), "Choose sculpted spell exclusions.")
        sculpt = [resolve_reference(world, aid, key) for key in sculpt]
        if sculpt:
            require("sculpt_spells" in actor["rpg"]["features"] and spec.get("school") == "evocation" and spec["target"] in {"cone", "cube", "area"}
                    and len(set(sculpt)) == len(sculpt) <= 1 + level and set(sculpt) <= set(targets), "Those creatures cannot be protected by Sculpt Spells.")
        if spec["resolution"] == "attack":
            from .combat import spell_strikes
            strikes = []
            for target in targets:
                require(not any(effect.get("source") == target and effect.get("condition") == "charmed" for effect in world["effects"].values() if effect["target"] == aid), "You cannot harm the creature charming you.")
                ward = next((effect for effect in world["effects"].values() if effect["target"] == target and effect.get("condition") == "sanctuary"), None)
                if ward:
                    saved = check(world, aid, stat="wis", saving=True, difficulty=ward.get("save_dc") or 12)
                    emit(world, "check", aid, text="A saving throw to target a warded creature.", **saved)
                    if not saved["success"]:
                        continue
                effects = deepcopy(spec["effects"])
                for effect in effects:
                    if effect.get("dice") and effect["kind"] in {"damage", "heal"}:
                        count, sides, bonus = validate_dice(effect["dice"])
                        if slot > level and spec.get("upcast"):
                            extra, extra_sides, _ = validate_dice(spec["upcast"])
                            require(extra_sides == sides, "This scaling rule needs matching dice.")
                            count += extra * (slot - level)
                        if spec.get("add_casting"):
                            bonus += modifier(actor, stat)
                        effect["dice"] = f"{count}d{sides}{bonus:+d}"
                strikes.append({"source": aid, "target": target, "stat": stat, "ranged": mechanic != "spiritual_strike", "effects": effects,
                    "cause": event["sequence"], "metadata": {"origin": key, "concentration": concentration, "repeat_save": spec.get("repeat_save"), "save_dc": dc, "breaks_on": spec.get("breaks_on")}})
            spell_strikes(world, strikes)
            return event
        for target in targets:
            if target in sculpt:
                continue
            if spec.get("hostile"):
                require(not any(effect.get("source") == target and effect.get("condition") == "charmed" for effect in world["effects"].values() if effect["target"] == aid), "You cannot harm the creature charming you.")
                sanctuary = next((effect for effect in world["effects"].values() if effect["target"] == target and effect.get("condition") == "sanctuary"), None)
                if sanctuary and spec["target"] == "creature":
                    ward = check(world, aid, stat="wis", saving=True, difficulty=sanctuary.get("save_dc") or 12)
                    emit(world, "check", aid, text="A saving throw to target a warded creature.", **ward)
                    if not ward["success"]:
                        continue
            effects = deepcopy(spec["effects"])
            saved = False
            if spec["resolution"] == "save":
                if mechanic == "turn_undead" and world["actors"][target]["species"] != "undead":
                    continue
                result = check(world, target, stat=spec["save"], difficulty=dc, saving=True)
                emit(world, "check", target, text=f"{world['actors'][target]['name']} saves against {spec['name']}.", **result)
                saved = result["success"]
                if saved and not spec.get("half_save"):
                    continue
            if mechanic == "turn_undead":
                effects = [{"kind": "condition", "condition": "turned", "duration": 10}]
            if mechanic == "command":
                effects = [{"kind": "condition", "condition": "commanded", "duration": 2}]
                world["actors"][target]["rpg"]["command"] = {"word": intent["command"], "source": aid, "turns": 1}
            for effect in effects:
                if "dice" in effect and slot > level and spec.get("upcast"):
                    count, sides, bonus = validate_dice(effect["dice"])
                    extra, extra_sides, _ = validate_dice(spec["upcast"])
                    require(extra_sides == sides, "This scaling rule needs matching dice.")
                    effect["dice"] = f"{count + extra * (slot - level)}d{sides}" + (f"{bonus:+d}" if bonus else "")
                if spec.get("add_casting") and effect["kind"] in {"heal", "damage"}:
                    bonus = modifier(actor, stat)
                    if effect["kind"] == "heal" and level and "disciple_of_life" in actor["rpg"]["features"]:
                        bonus += 2 + slot
                    count, sides, original = validate_dice(effect["dice"])
                    effect["dice"] = f"{count}d{sides}{original + bonus:+d}"
                if effect["kind"] == "heal":
                    require(world["actors"][target]["species"] not in {"undead", "construct"}, "This healing spell does not affect undead or constructs.")
                if saved and effect["kind"] == "damage":
                    rolled = dice(world, effect.pop("dice")) if "dice" in effect else None
                    effect["amount"] = (rolled["total"] if rolled else effect["amount"]) // 2
                    if rolled:
                        emit(world, "damage_roll", aid, targets=[target], text="Damage is halved on the save.", dice=rolled)
                apply_effect(world, aid, target, effect, origin=key, concentration=concentration,
                             repeat_save=spec.get("repeat_save"), save_dc=dc, breaks_on=spec.get("breaks_on"))
            if spec["economy"] == "reaction" and world["combat"]:
                for effect in world["effects"].values():
                    if effect.get("origin") == key and effect["source"] == aid:
                        effect.update(until_turn_actor=aid, until_turn_serial=world["combat"]["turn_serial"], ends_at=world["tick"] + 2)
            if mechanic == "thunderwave" and not saved and world["actors"][target]["hp"] > 0:
                body = world["actors"][target]
                for _ in range(2):
                    dx, dy = body["position"][0] - actor["position"][0], body["position"][1] - actor["position"][1]
                    step = [body["position"][0] + (1 if dx > 0 else -1 if dx < 0 else 0), body["position"][1]] if abs(dx) >= abs(dy) else [body["position"][0], body["position"][1] + (1 if dy > 0 else -1)]
                    if step == body["position"] or not walkable(world, step):
                        break
                    apply_effect(world, aid, target, {"kind": "move", "position": step, "distance": 1})
        if mechanic == "thunderwave":
            apply_effect(world, aid, aid, {"kind": "sound", "volume": 24})
        return event
    finally:
        if old_cause is None:
            world.pop("_cause", None)
        else:
            world["_cause"] = old_cause


def resolve_special(world, aid, spec, intent, targets, point, slot, stat):
    from .combat import turn_budget
    actor = world["actors"][aid]
    mechanic = spec.get("mechanic")
    if mechanic == "second_wind":
        apply_effect(world, aid, aid, {"kind": "heal", "dice": f"1d10+{class_level(actor, 'fighter')}"})
    elif mechanic == "action_surge":
        require(world["combat"] is not None, "Action Surge requires an encounter turn.")
        turn_budget(world, aid)["action"] += 1
    elif mechanic == "dash":
        from .characters import speed
        require(world["combat"] is not None, "Use travel outside combat.")
        turn_budget(world, aid)["movement"] += speed(world, aid)
    elif mechanic == "disengage":
        apply_effect(world, aid, aid, {"kind": "condition", "condition": "disengaged", "duration": 2}, origin=spec["id"])
        if world["combat"]:
            for effect in world["effects"].values():
                if effect.get("origin") == spec["id"] and effect["target"] == aid:
                    effect.update(until_turn_actor=aid, until_turn_serial=world["combat"]["turn_serial"])
    elif mechanic == "hide":
        require(actor["position"] in world["map"].get("concealment_tiles", []) or not any(other != aid and can_identify(world, other, aid) for other in world["actors"]), "You need concealment before hiding.")
        result = check(world, aid, skill="stealth", difficulty=0)
        actor["rpg"]["hidden"] = result["total"]
        emit(world, "check", aid, text=f"{actor['name']} hides.", **result)
    elif mechanic == "fast_hands":
        from .actions import apply_action
        target = targets[0]
        obj = world["items"].get(target)
        require(not obj or not item_rules(world, obj).get("magic"), "Fast Hands cannot activate magic items.")
        apply_action(world, aid, {"kind": "use", "target": target, **{key: intent[key] for key in ("recipient", "object", "open") if key in intent}}, _paid=True)
    elif mechanic == "preserve_life":
        pool = 5 * class_level(actor, "cleric")
        allocations = intent.get("allocations")
        require(allocations is None or isinstance(allocations, list) and len(allocations) == len(targets) and all(type(n) is int and n >= 0 for n in allocations)
                and sum(allocations) <= pool, "Distribute the available healing pool among the selected creatures.")
        for index, target in enumerate(targets):
            body = world["actors"][target]
            require(body["species"] not in {"undead", "construct"}, "Preserve Life cannot heal that creature type.")
            amount = min(pool, max(0, body["max_hp"] // 2 - body["hp"]))
            if allocations:
                require(allocations[index] <= amount, "Preserve Life cannot restore more than half maximum HP.")
                amount = allocations[index]
            apply_effect(world, aid, target, {"kind": "heal", "amount": amount})
            pool -= amount
    elif mechanic == "arcane_recovery":
        for level in intent.get("slots", [1]):
            value = actor["rpg"]["resources"][f"slot_{level}"]
            require(value["current"] < value["max"], "That slot is already full.")
            value["current"] += 1
        actor["rpg"]["arcane_recovery_day"] = world["tick"] // 14400
    elif mechanic == "light":
        target = targets[0]
        obj = world["items"].get(target, world["fixtures"].get(target))
        for existing in list(world["items"].values()) + list(world["fixtures"].values()):
            if existing.get("light", {}).get("source") == aid:
                existing.pop("light", None)
        obj["light"] = {"source": aid, "ends_at": world["tick"] + spec["duration"], "radius": 4}
    elif mechanic == "mage_hand":
        require(walkable(world, point), "The hand's destination is blocked.")
        hand = actor["rpg"].get("mage_hand")
        iid = intent.get("item")
        if iid:
            require(hand and hand["ends_at"] > world["tick"], "Summon the hand before manipulating an object.")
            obj = world["items"].get(iid)
            position = item_position(world, obj) if obj else None
            require(obj and obj["weight"] <= 1 and obj["kind"] != "container" and position is not None
                    and "carrier" not in obj["place"] and distance(position, hand["position"]) <= 1
                    and can_see(world, aid, position) and distance(point, hand["position"]) <= 6, "The hand can move one small unattended object within reach.")
            if "container" in obj["place"]:
                require(world["fixtures"][obj["place"]["container"]].get("open"), "The container is closed.")
            obj["place"] = {"ground": point[:]}
            emit(world, "put", aid, targets=[iid], position=point, text=f"The spectral hand moves {obj['name']}.", item_place=deepcopy(obj["place"]))
            hand["position"] = point[:]
        else:
            actor["rpg"]["mage_hand"] = {"position": point[:], "ends_at": world["tick"] + spec["duration"]}
    elif mechanic == "magic_missile":
        from .combat import spell_strikes
        targets = [target for target in targets if hostile_target_allowed(world, aid, target)]
        if not targets:
            return True
        rolled = dice(world, "1d4+1")
        amounts = {target: 0 for target in targets}
        for index in range(3 + slot - 1):
            target = targets[index % len(targets)]
            amounts[target] += rolled["total"]
        emit(world, "damage_roll", aid, targets=targets, text="Magic missiles strike together.", dice=rolled)
        spell_strikes(world, [{"source": aid, "target": target, "missiles": True, "cause": world.get("_cause"),
            "effects": [{"kind": "damage", "amount": amount, "damage_type": "force"}], "metadata": {"origin": spec["id"]}}
            for target, amount in amounts.items()])
    elif mechanic == "restoration":
        apply_effect(world, aid, targets[0], {"kind": "remove_condition", "condition": intent["condition"]})
    elif mechanic == "spiritual_weapon":
        actor["rpg"]["spiritual_weapon"] = {"position": point[:], "ends_at": world["tick"] + 10, "slot": slot, "stat": stat}
        if intent.get("target"):
            target = resolve_reference(world, aid, intent["target"])
            require(target in world["actors"] and distance(world["actors"][target]["position"], point) <= 1 and can_identify(world, aid, target), "The new spiritual weapon cannot reach that target.")
            from .combat import spell_strikes
            if not hostile_target_allowed(world, aid, target):
                break_effects(world, aid, "attack_or_spell")
                return True
            spell_strikes(world, [{"source": aid, "target": target, "stat": stat,
                "effects": [{"kind": "damage", "dice": f"1d8{modifier(actor, stat):+d}", "damage_type": "force"}],
                "cause": world.get("_cause"), "metadata": {"origin": spec["id"]}}])
        else:
            break_effects(world, aid, "attack_or_spell", harmful=False)
    elif mechanic == "misty_step":
        apply_effect(world, aid, aid, {"kind": "move", "position": point, "teleport": True, "distance": 6})
    else:
        return False
    return True


def hostile_target_allowed(world, aid, target):
    require(not any(effect.get("source") == target and effect.get("condition") == "charmed"
                    for effect in world["effects"].values() if effect["target"] == aid), "You cannot harm the creature charming you.")
    ward = next((effect for effect in world["effects"].values() if effect["target"] == target and effect.get("condition") == "sanctuary"), None)
    if ward:
        saved = check(world, aid, stat="wis", saving=True, difficulty=ward.get("save_dc") or 12)
        emit(world, "check", aid, text="A saving throw to target a warded creature.", **saved)
        return saved["success"]
    return True
