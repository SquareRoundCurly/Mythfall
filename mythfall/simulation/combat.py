"""Party initiative, action economy and shared weapon resolution.

This module never chooses an NPC's tactics. It yields an actor decision boundary.
"""

from copy import deepcopy

from .catalog import class_level, item_rules
from .characters import armor_class, passive_bonus, prepared_abilities, speed
from .checks import check, dice, modifier, proficiency, validate_dice
from .effects import apply_effect, break_effects, damage, end_concentration, remove_effect
from .migration import allocate_id
from .minds import active_effects, can_identify, has_condition, reference, relationship_change, appearance
from .state import PLAYER, distance, emit, require, roll

MAX_COMBATANTS = 8


def incapacitated(world, aid):
    return world["actors"][aid]["hp"] <= 0 or any(has_condition(world, aid, name)
        for name in ("incapacitated", "stunned", "paralyzed", "unconscious"))


def side(world, aid):
    combat = world.get("combat")
    participant = next((entry for entry in (combat or {}).get("participants", []) if entry["id"] == aid), None)
    return participant["side"] if participant else "party" if aid in world["party"]["members"] else aid


def turn_budget(world, aid):
    require(world.get("combat") is not None and aid in world["combat"]["economy"], "That actor is outside this encounter.")
    return world["combat"]["economy"][aid]


def start(world, initiator, targets):
    if world["combat"]:
        for aid in targets:
            if aid not in world["combat"]["economy"]:
                join(world, aid, "party" if aid in world["party"]["members"] else "hostile")
        return
    members = list(dict.fromkeys([initiator] + list(targets)))
    for aid in world["party"]["members"]:
        if aid not in members and any(can_identify(world, aid, other) for other in members):
            members.append(aid)
    require(len(members) <= MAX_COMBATANTS, "The active encounter supports eight participants.")
    combat = {"id": allocate_id(world, "encounter"), "participants": [], "turn": 0, "round": 1,
              "turn_serial": 1, "started_at": world["tick"], "economy": {}, "pending": None, "awaiting": None}
    world["combat"] = combat
    for aid in members:
        faction = "party" if aid in world["party"]["members"] else "initiator" if aid == initiator and initiator not in world["party"]["members"] and not any(target in world["party"]["members"] for target in targets) else "hostile"
        join(world, aid, faction, initial=True)
    combat["participants"].sort(key=lambda entry: (-entry["initiative"], -modifier(world["actors"][entry["id"]], "dex"), entry["id"]))
    begin_turn(world)
    emit(world, "encounter", initiator, text="An encounter begins. Initiative is rolled.", targets=targets)


def join(world, aid, faction, *, initial=False):
    combat = world["combat"]
    require(aid in world["actors"] and world["actors"][aid]["life"] != "dead", "That actor cannot join combat.")
    if aid in combat["economy"]:
        return
    require(len(combat["participants"]) < MAX_COMBATANTS, "The encounter is at its active cast limit.")
    rolled = check(world, aid, stat="dex", difficulty=0)
    combat["participants"].append({"id": aid, "side": faction, "initiative": rolled["total"], "die": rolled["die"]})
    combat["economy"][aid] = {"action": 0, "bonus": 0, "reaction": 1, "movement": 0, "interaction": 0, "speech": 0, "cast_bonus": False, "cast_levelled": False}
    world["actors"][aid]["plan"] = None
    if not initial:
        emit(world, "combat_join", aid, text=f"{world['actors'][aid]['name']} joins the encounter.")


def begin_turn(world):
    combat = world["combat"]
    aid = combat["participants"][combat["turn"]]["id"]
    for entry in combat["economy"].values():
        entry["sneak"] = False
    combat["awaiting"] = aid
    budget = combat["economy"][aid]
    budget.update(action=1, bonus=1, reaction=1, movement=speed(world, aid), interaction=1, speech=1,
                  cast_bonus=False, cast_levelled=False, sneak=False, attacked=False)
    # Turn-scoped effects expire when their owner next receives a turn.
    for eid, effect in list(world["effects"].items()):
        if effect.get("until_turn_actor") == aid and effect.get("until_turn_serial", 0) < combat["turn_serial"]:
            remove_effect(world, eid)
    actor = world["actors"][aid]
    if actor["life"] == "unconscious" and not has_condition(world, aid, "stable"):
        death_save(world, aid)
    command = actor["rpg"].get("command") if has_condition(world, aid, "commanded") else None
    if command and command["word"] in {"halt", "grovel", "drop"}:
        if command["word"] == "grovel":
            apply_effect(world, aid, aid, {"kind": "condition", "condition": "prone", "duration": 14400})
        if command["word"] == "drop":
            from .actions import apply_action
            held = set(key for key in (actor["equipped"], actor["rpg"].get("shield"), actor["rpg"].get("offhand")) if key)
            budget["interaction"] = len(held)
            for iid in held:
                apply_action(world, aid, {"kind": "drop", "target": iid})
        budget.update(action=0, bonus=0, movement=0, interaction=0)
    emit(world, "turn", aid, text=f"{actor['name']}'s turn (round {combat['round']}).")


def death_save(world, aid):
    actor = world["actors"][aid]
    value = roll(world, 20)
    saves = actor["rpg"]["death_saves"]
    if value == 20:
        apply_effect(world, aid, aid, {"kind": "heal", "amount": 1})
    else:
        saves["success" if value >= 10 else "failure"] += 2 if value == 1 else 1
        if saves["failure"] >= 3:
            actor.update(life="dead", activity="dead", remains={"nutrition": 5000, "consumed": False})
            emit(world, "death", aid, text=f"{actor['name']} dies.")
        elif saves["success"] >= 3:
            duration = dice(world, "1d4")["total"] * 600
            apply_effect(world, aid, aid, {"kind": "condition", "condition": "stable", "duration": duration})
            saves.update(success=0, failure=0)
    emit(world, "death_save", aid, text=f"{actor['name']} rolls a death saving throw: {value}.", die=value)


def end_turn(world):
    combat = world["combat"]
    require(combat is not None and combat["pending"] is None, "Resolve the pending reaction first.")
    aid = combat["awaiting"]
    if world["actors"][aid]["rpg"].pop("command", None):
        for eid, effect in list(world["effects"].items()):
            if effect["target"] == aid and effect.get("condition") == "commanded":
                remove_effect(world, eid)
    for eid, effect in list(world["effects"].items()):
        if effect["target"] == aid and effect.get("repeat_save") and world["actors"][aid]["hp"] > 0:
            result = check(world, aid, stat=effect["repeat_save"], saving=True, difficulty=effect["save_dc"])
            emit(world, "check", aid, text="A saving throw against an ongoing effect.", **result)
            if result["success"]:
                remove_effect(world, eid)
    combat["turn"] = (combat["turn"] + 1) % len(combat["participants"])
    combat["turn_serial"] += 1
    wrapped = combat["turn"] == 0
    if wrapped:
        combat["round"] += 1
    return wrapped


def validate_compulsion(world, aid, intent):
    actor = world["actors"][aid]
    kind = intent.get("kind")
    command = actor["rpg"].get("command") if has_condition(world, aid, "commanded") else None
    turned = next((effect for effect in active_effects(world, aid) if effect.get("condition") == "turned"), None)
    fear = next((effect for effect in active_effects(world, aid) if effect.get("condition") == "frightened" and effect["source"] in world["actors"] and can_identify(world, aid, effect["source"])), None)
    if command and command["word"] in {"halt", "grovel", "drop"}:
        require(kind in {"end_turn", "inspect"}, "The command consumes this turn.")
    if turned or command and command["word"] in {"flee", "approach"}:
        require(kind in {"move", "dash", "dodge", "end_turn", "inspect"}, "This compulsion limits you to movement, Dash, or Dodge when blocked.")
    if kind == "move" and isinstance(intent.get("position"), list) and len(intent["position"]) == 2 and all(type(n) is int for n in intent["position"]):
        source = (turned or fear or command or {}).get("source")
        if source in world["actors"]:
            before = distance(actor["position"], world["actors"][source]["position"])
            after = distance(intent["position"], world["actors"][source]["position"])
            require(after <= before if command and command["word"] == "approach" else after >= before, "That move conflicts with the active condition.")


def finish_if_resolved(world):
    combat = world.get("combat")
    if not combat or combat.get("pending"):
        return False
    living_sides = {entry["side"] for entry in combat["participants"]
                    if world["actors"][entry["id"]]["hp"] > 0 and not entry.get("withdrawn")}
    active = [entry for entry in combat["participants"] if world["actors"][entry["id"]]["hp"] > 0 and not entry.get("withdrawn")]
    truce = bool(active) and all(entry.get("peace_offer") for entry in active)
    if len(living_sides) > 1 and not truce:
        return False
    world.setdefault("encounters", []).append({**deepcopy(combat), "ended_at": world["tick"], "winner": None if truce else next(iter(living_sides), None), "outcome": "truce" if truce else "resolved"})
    world["combat"] = None
    emit(world, "encounter_end", PLAYER, text="Everyone still fighting agrees to a truce." if truce else "The encounter ends.")
    return True


def break_truce(world):
    if world["combat"]:
        for entry in world["combat"]["participants"]:
            entry.pop("peace_offer", None)


def pay(world, aid, economy):
    if not world["combat"]:
        require(economy != "reaction", "A reaction needs its triggering event.")
        return
    combat = world["combat"]
    budget = turn_budget(world, aid)
    if economy == "reaction":
        require(combat.get("pending") and combat["pending"].get("reactor") == aid, "No reaction is awaiting you.")
    else:
        require(combat["awaiting"] == aid and combat.get("pending") is None, "Wait for your turn or resolve the reaction.")
    require(not incapacitated(world, aid), "An incapacitated character cannot act.")
    if economy != "free":
        require(budget.get(economy, 0) > 0, f"No {economy} remains this turn.")
        budget[economy] -= 1


def attack_roll(world, aid, target, *, stat=None, trained=True, bonus=0, ranged=False, long=False, disadvantage=False):
    actor = world["actors"][aid]
    defender = world["actors"][target]
    advantages = []
    disadvantages = [disadvantage]
    advantages.append(not can_identify(world, target, aid))
    advantages.append(any(has_condition(world, target, name) for name in ("restrained", "stunned", "paralyzed", "unconscious")))
    disadvantages.append(any(has_condition(world, aid, name) for name in ("blinded", "poisoned", "restrained", "prone", "frightened")))
    disadvantages.append(has_condition(world, target, "guarded") and can_identify(world, target, aid))
    if has_condition(world, target, "prone"):
        (advantages if distance(actor["position"], defender["position"]) <= 1 else disadvantages).append(True)
    disadvantages.append(long)
    from .characters import untrained_armor
    disadvantages.append((stat or "str") in {"str", "dex"} and untrained_armor(world, aid))
    if ranged:
        disadvantages.append(any(other != aid and side(world, other) != side(world, aid)
                                  and distance(actor["position"], body["position"]) <= 1 and not incapacitated(world, other)
                                  for other, body in world["actors"].items() if can_identify(world, aid, other)))
    advantage = int(any(advantages)) - int(any(disadvantages))
    rolls = [roll(world, 20) for _ in range(2 if advantage else 1)]
    die = min(rolls) if advantage < 0 else max(rolls)
    bonus_rolls = []
    for effect in active_effects(world, aid, "check_bonus"):
        if effect.get("attack"):
            bonus_rolls.append(dice(world, effect["dice"]))
    mod = modifier(actor, stat or "str") + (proficiency(actor) if trained else 0) + bonus + sum(r["total"] for r in bonus_rolls)
    armor = armor_class(world, target)
    critical = die >= (19 if "improved_critical" in actor["rpg"]["features"] and stat is None else 20)
    critical |= any(has_condition(world, target, condition) for condition in ("paralyzed", "unconscious")) and distance(actor["position"], defender["position"]) <= 1
    return {"die": die, "rolls": rolls, "modifier": mod, "total": die + mod, "armor": armor,
            "hit": die != 1 and (die == 20 or die + mod >= armor), "critical": critical, "advantage": advantage, "bonuses": bonus_rolls}


def weapon_attack(world, aid, target, *, nonlethal=False, offhand=False, reaction=False, paid=False, protect=True, disadvantage=False, after_move=None):
    actor = world["actors"][aid]
    require(target in world["actors"] and target != aid, "Choose another creature.")
    defender = world["actors"][target]
    require(defender["life"] != "dead" and (can_identify(world, aid, target) or defender["hp"] == 0), "You cannot target that creature.")
    require(not any(effect.get("condition") == "charmed" and effect["source"] == target for effect in active_effects(world, aid)), "You cannot attack the creature charming you.")
    iid = actor["rpg"].get("offhand") if offhand else actor["equipped"]
    weapon = world["items"].get(iid)
    spec = item_rules(world, weapon) if weapon else {"dice": "1d4", "damage_type": "bludgeoning", "unarmed": True}
    reach = spec.get("long_range", spec.get("range", 1))
    separation = distance(actor["position"], defender["position"])
    require(separation <= reach, "The target is out of weapon range.")
    require(not spec.get("two_handed") or not actor["rpg"].get("shield"), "Stow your shield to use this two-handed weapon.")
    ammo = None
    if spec.get("ammo") and not paid:
        ammo = next((item for item in world["items"].values() if item["place"].get("carrier") == aid
                     and item_rules(world, item).get("ammo") == spec["ammo"] and item["kind"] == "ammunition"), None)
        require(ammo is not None, "No ammunition remains.")
    if offhand:
        primary = world["items"].get(actor["equipped"])
        require(primary and item_rules(world, primary).get("light") and spec.get("light")
                and turn_budget(world, aid).get("attacked"), "Two-weapon fighting requires two light weapons and an Attack action first.")
    economy = "reaction" if reaction else "bonus" if offhand else "action"
    if world["combat"] is None:
        start(world, aid, [target])
        if world["combat"]["awaiting"] != aid:
            return emit(world, "initiative_wait", aid, text="Initiative is rolled; the first participant must act before this attack.")
    if not paid:
        pay(world, aid, economy)
        break_truce(world)
    if ammo:
        ammo["place"] = {"consumed": True}
    sanctuary = next((effect for effect in active_effects(world, target) if effect.get("condition") == "sanctuary"), None)
    if sanctuary and not paid:
        ward = check(world, aid, stat="wis", saving=True, difficulty=sanctuary.get("save_dc") or 12)
        emit(world, "check", aid, text="A saving throw to target a warded creature.", **ward)
        if not ward["success"]:
            if after_move:
                continue_move(world, after_move)
            return emit(world, "warded", aid, targets=[target], text="The ward prevents the attack.")
    if protect and world["combat"]:
        protector = next((other for other in sorted(world["combat"]["economy"]) if other != target and side(world, other) == side(world, target)
                          and world["actors"][other]["rpg"].get("style") == "protection" and world["actors"][other]["rpg"].get("shield")
                          and distance(world["actors"][other]["position"], defender["position"]) <= 1 and can_identify(world, other, aid)
                          and not incapacitated(world, other) and turn_budget(world, other)["reaction"] > 0), None)
        if protector:
            world["combat"]["pending"] = {"kind": "protection", "source": aid, "target": target, "reactor": protector,
                "nonlethal": nonlethal, "offhand": offhand, "after_move": after_move}
            return emit(world, "reaction", protector, targets=[target], text="A nearby ally can be protected with a shield.")
    ranged = spec.get("ranged", False)
    stat = "dex" if ranged or spec.get("finesse") and modifier(actor, "dex") > modifier(actor, "str") else "str"
    trained = spec.get("unarmed") or spec.get("category") in actor["rpg"]["weapon_proficiencies"] or spec.get("weapon") in actor["rpg"]["weapon_proficiencies"]
    style = actor["rpg"].get("style")
    bonus = spec.get("bonus", 0) + (2 if ranged and style == "archery" else 0)
    result = attack_roll(world, aid, target, stat=stat, trained=trained, bonus=bonus, ranged=ranged, long=separation > spec.get("range", 1), disadvantage=disadvantage)
    if "improved_critical" in actor["rpg"]["features"] and result["die"] == 19:
        result.update(critical=True, hit=True, automatic_hit=True)
    rolled = dice(world, spec["dice"])
    if style == "great_weapon" and spec.get("two_handed") and not ranged:
        rolled["rolls"] = [roll(world, validate_dice(spec["dice"])[1]) if n <= 2 else n for n in rolled["rolls"]]
        rolled["total"] = sum(rolled["rolls"]) + rolled["bonus"]
    amount = (1 if spec.get("unarmed") else rolled["total"])
    if result["critical"] and not spec.get("unarmed"):
        extra = dice(world, spec["dice"])
        amount += extra["total"] - extra["bonus"]
        rolled["critical_dice"] = extra
    ability_mod = modifier(actor, stat)
    amount += ability_mod if not offhand or style == "two_weapon" or ability_mod < 0 else 0
    amount += spec.get("bonus", 0) + (2 if style == "dueling" and not ranged and not actor["rpg"].get("offhand") and not spec.get("two_handed") else 0)
    budget = turn_budget(world, aid) if world["combat"] else {}
    ally_near = any(other != aid and side(world, other) == side(world, aid) and distance(body["position"], defender["position"]) <= 1
                   and not incapacitated(world, other) for other, body in world["actors"].items())
    if class_level(actor, "rogue") and (spec.get("finesse") or ranged) and not budget.get("sneak") and result["advantage"] >= 0 and (result["advantage"] > 0 or ally_near):
        sneak = dice(world, f"{((class_level(actor, 'rogue') + 1) // 2) * (2 if result['critical'] else 1)}d6")
        amount += sneak["total"]
        rolled["sneak_attack"] = sneak
        if result["hit"]:
            budget["sneak"] = True
    budget["attacked"] = True
    break_effects(world, aid, "attack_or_spell")
    pending = {"kind": "weapon", "source": aid, "target": target, "roll": result, "dice": rolled,
               "amount": max(0, amount), "damage_type": spec.get("damage_type", "bludgeoning"),
               "nonlethal": nonlethal and not ranged}
    if after_move:
        pending["after_move"] = after_move
    if result["hit"] and can_shield(world, target):
        pending["reactor"] = target
        world["combat"]["pending"] = pending
        return emit(world, "reaction", target, targets=[aid], text="A hit allows a Shield reaction.", **result)
    return finish_attack(world, pending)


def can_shield(world, aid):
    if not world["combat"] or aid not in world["combat"]["economy"] or incapacitated(world, aid):
        return False
    actor = world["actors"][aid]
    from .characters import casting_unavailable
    return (turn_budget(world, aid)["reaction"] > 0 and "ability.shield@1" in prepared_abilities(world, aid)
            and casting_unavailable(world, aid, world["definitions"]["ability.shield@1"]) is None
            and not (world["combat"]["awaiting"] == aid and turn_budget(world, aid).get("cast_bonus"))
            and any(key.startswith("slot_") and value["current"] > 0 for key, value in actor["rpg"]["resources"].items()))


def spell_strikes(world, strikes, *, protected=False, disadvantage=False):
    """Resolve a persisted sequence, yielding before a reaction's consequences."""
    if not strikes:
        return None
    strike, remaining = deepcopy(strikes[0]), deepcopy(strikes[1:])
    aid, target = strike["source"], strike["target"]
    if world["actors"][target]["life"] == "dead":
        return spell_strikes(world, remaining)
    if strike.get("missiles"):
        if not has_condition(world, target, "shielded") and can_shield(world, target):
            world["combat"]["pending"] = {"kind": "missiles", "reactor": target, **strike, "remaining": remaining}
            return emit(world, "reaction", target, text="Incoming magic missiles allow a Shield reaction.")
        return finish_spell(world, {**strike, "remaining": remaining})
    if not protected and world["combat"]:
        protector = next((other for other in sorted(world["combat"]["economy"]) if other != target and side(world, other) == side(world, target)
            and world["actors"][other]["rpg"].get("style") == "protection" and world["actors"][other]["rpg"].get("shield")
            and distance(world["actors"][other]["position"], world["actors"][target]["position"]) <= 1 and can_identify(world, other, aid)
            and not incapacitated(world, other) and turn_budget(world, other)["reaction"] > 0), None)
        if protector:
            world["combat"]["pending"] = {"kind": "spell_protection", "reactor": protector, "source": aid, "target": target, "strikes": [strike] + remaining}
            return emit(world, "reaction", protector, targets=[target], text="A nearby ally can be protected from the spell attack.")
    result = attack_roll(world, aid, target, stat=strike["stat"], ranged=strike.get("ranged", False), disadvantage=disadvantage)
    break_effects(world, aid, "attack_or_spell")
    pending = {**strike, "kind": "spell", "roll": result, "remaining": remaining}
    if result["hit"] and can_shield(world, target):
        world["combat"]["pending"] = {**pending, "reactor": target}
        return emit(world, "reaction", target, targets=[aid], text="A spell hit allows a Shield reaction.", **result)
    return finish_spell(world, pending)


def finish_spell(world, pending):
    aid, target = pending["source"], pending["target"]
    if pending.get("missiles"):
        hit = not has_condition(world, target, "shielded")
        result = {}
    else:
        result = pending["roll"]
        armor = armor_class(world, target)
        hit = result["die"] != 1 and (result["die"] == 20 or result["total"] >= armor)
        result = {**result, "armor": armor}
    event = emit(world, "spell_attack", aid, targets=[target], text=f"The spell {'hits' if hit else 'misses or is blocked'}.", **{**result, "hit": hit})
    previous = world.get("_cause")
    world["_cause"] = pending.get("cause", event["sequence"])
    try:
        if hit:
            from .checks import validate_dice
            for effect in deepcopy(pending["effects"]):
                if result.get("critical") and effect["kind"] == "damage" and effect.get("dice"):
                    count, sides, bonus = validate_dice(effect["dice"])
                    effect["dice"] = f"{count * 2}d{sides}{bonus:+d}"
                apply_effect(world, aid, target, effect, critical=bool(result.get("critical")), **pending.get("metadata", {}))
        if can_identify(world, target, aid):
            relationship_change(world, target, aid, -10 - world["actors"][target]["relationships"].get(aid, 0), event["sequence"])
        world["actors"][target]["plan"] = None
        return spell_strikes(world, pending.get("remaining", [])) or event
    finally:
        if previous is None:
            world.pop("_cause", None)
        else:
            world["_cause"] = previous


def finish_attack(world, pending):
    source, target, result = pending["source"], pending["target"], pending["roll"]
    armor = armor_class(world, target)
    hit = result["die"] != 1 and (result["die"] == 20 or result.get("automatic_hit") or result["total"] >= armor)
    defender = world["actors"][target]
    if hit:
        damage(world, source, target, pending["amount"], damage_type=pending["damage_type"], nonlethal=pending.get("nonlethal", False), critical=result.get("critical", False))
    defender["plan"] = None
    event = emit(world, "attack", source, targets=[target], text=f"{world['actors'][source]['name']} {'hits' if hit else 'misses'} {defender['name']}.",
                **{**result, "hit": hit, "armor": armor}, damage=pending["amount"] if hit else 0, hp=defender["hp"], dice=pending["dice"])
    if can_identify(world, target, source):
        relationship_change(world, target, source, -10 - defender["relationships"].get(source, 0), event["sequence"])
    if pending.get("after_move"):
        continue_move(world, pending["after_move"])
    return event


def reaction(world, aid, intent):
    combat = world["combat"]
    require(combat and combat["pending"] and combat["pending"]["reactor"] == aid, "No reaction awaits that character.")
    pending = combat["pending"]
    choice = intent.get("ability")
    if pending["kind"] == "spell_protection":
        require(choice in {None, "feature.protection"}, "Protect your ally or pass.")
        if choice:
            pay(world, aid, "reaction")
        combat["pending"] = None
        return spell_strikes(world, pending["strikes"], protected=True, disadvantage=bool(choice))
    if pending["kind"] == "protection":
        require(choice in {None, "feature.protection"}, "Protect your ally or pass.")
        if choice:
            pay(world, aid, "reaction")
        combat["pending"] = None
        return weapon_attack(world, pending["source"], pending["target"], nonlethal=pending["nonlethal"], offhand=pending["offhand"],
                             paid=True, protect=False, disadvantage=bool(choice), after_move=pending.get("after_move"))
    if pending["kind"] == "opportunity":
        require(choice in {None, "action.attack"}, "Make the opportunity attack or pass.")
        if choice:
            return weapon_attack(world, aid, pending["target"], reaction=True, protect=False, after_move=pending["after_move"])
        combat["pending"] = None
        return continue_move(world, pending["after_move"])
    if intent.get("ability"):
        require(intent["ability"] == "ability.shield@1", "This trigger allows Shield or passing.")
        from .abilities import activate
        slot = intent.get("slot") or next(n for n in (1, 2) if world["actors"][aid]["rpg"]["resources"].get(f"slot_{n}", {}).get("current", 0))
        activate(world, aid, {"kind": "ability", "ability": intent["ability"], "slot": slot})
    combat["pending"] = None
    if pending["kind"] in {"spell", "missiles"}:
        return finish_spell(world, pending)
    return finish_attack(world, pending)


def movement_reactions(world, aid, point):
    combat = world["combat"]
    if not combat or has_condition(world, aid, "disengaged"):
        return None
    candidates = [other for other in sorted(combat["economy"]) if side(world, other) != side(world, aid)
                  and not incapacitated(world, other) and turn_budget(world, other)["reaction"] > 0
                  and distance(world["actors"][other]["position"], world["actors"][aid]["position"]) <= 1
                  and distance(world["actors"][other]["position"], point) > 1 and can_identify(world, other, aid)]
    if not candidates:
        return None
    return continue_move(world, {"actor": aid, "position": point[:], "remaining": candidates})


def continue_move(world, movement):
    combat = world["combat"]
    actor = world["actors"][movement["actor"]]
    if actor["hp"] <= 0 or speed(world, actor["id"]) == 0:
        if combat:
            combat["pending"] = None
        return emit(world, "movement_stopped", actor["id"], text="The movement is interrupted.")
    while movement["remaining"]:
        aid = movement["remaining"].pop(0)
        if combat and not incapacitated(world, aid) and turn_budget(world, aid)["reaction"] > 0:
            combat["pending"] = {"kind": "opportunity", "reactor": aid, "target": actor["id"], "source": aid, "after_move": deepcopy(movement)}
            return emit(world, "reaction", aid, targets=[actor["id"]], text="A creature leaving reach allows an opportunity attack.")
    if combat:
        combat["pending"] = None
    actor["position"] = movement["position"][:]
    return emit(world, "move", actor["id"], position=actor["position"], text=f"{actor['name']} moves.")


def public_combat(world, observer):
    combat = world.get("combat")
    if not combat:
        return None
    result = {key: combat[key] for key in ("id", "round", "turn_serial", "started_at")}
    result["awaiting"] = reference(world, observer, combat["awaiting"]) if can_identify(world, observer, combat["awaiting"]) or observer == combat["awaiting"] else "unknown"
    result["participants"] = [{**{k: v for k, v in entry.items() if k != "id"}, "id": reference(world, observer, entry["id"])}
                              for entry in combat["participants"] if entry["id"] == observer or can_identify(world, observer, entry["id"])]
    for entry, actual in zip(result["participants"], [entry for entry in combat["participants"] if entry["id"] == observer or can_identify(world, observer, entry["id"])]):
        identity, _ = appearance(world, observer, actual["id"])
        if identity != actual["id"]:
            entry["side"] = side(world, identity) if identity in world["actors"] else "unknown"
    result["economy"] = deepcopy(combat["economy"].get(observer))
    if combat["pending"] and combat["pending"]["reactor"] == observer:
        pending = combat["pending"]
        result["reaction"] = {"kind": pending["kind"], "options": [{"protection": "feature.protection", "spell_protection": "feature.protection", "opportunity": "action.attack"}.get(pending["kind"], "ability.shield@1"), "pass"], "roll": deepcopy(pending.get("roll"))}
    return result
