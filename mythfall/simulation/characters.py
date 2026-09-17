"""Class choices, derived resources, equipment and recorded progression."""

from copy import deepcopy
from collections import Counter

from .catalog import CLASSES, SPELL_SLOTS, XP_THRESHOLDS, class_level, definition, item_rules
from .checks import integer, modifier, proficiency, dice
from .migration import allocate_id
from .state import PLAYER, distance, emit, require


def resource(actor, key, maximum, recovery):
    resources = actor["rpg"]["resources"]
    old = resources.get(key)
    resources[key] = {"current": min(maximum, old["current"] + max(0, maximum - old["max"])) if old else maximum,
                      "max": maximum, "recovery": recovery}


def spend(actor, key, amount=1):
    value = actor["rpg"]["resources"].get(key)
    require(value is not None and value["current"] >= amount, f"Not enough {key.replace('_', ' ')} remaining.")
    value["current"] -= amount


def casting_stat(actor, spec, chosen=None):
    eligible = [name for name in spec.get("classes", []) if class_level(actor, name)]
    if chosen:
        require(chosen in eligible, "That class cannot cast this spell.")
        return CLASSES[chosen]["casting"]
    return CLASSES[eligible[0]]["casting"] if eligible else actor["rpg"].get("casting", "wis")


def derive(actor):
    rpg = actor["rpg"]
    counts = Counter(rpg["classes"])
    features = set()
    granted = set()
    for name, level in counts.items():
        resource(actor, "hit_dice_" + name, level, "hit_dice")
        if name == "fighter":
            features.add("fighting_style")
            granted.add("second_wind")
            resource(actor, "second_wind", 1, "short")
            if level >= 2:
                granted.add("action_surge")
                resource(actor, "action_surge", 1, "short")
            if level >= 3:
                features.add("improved_critical")
        elif name == "rogue":
            features.update({"sneak_attack", "expertise", "thieves_cant"})
            if level >= 2:
                granted.update({"cunning_dash", "cunning_disengage", "cunning_hide"})
            if level >= 3:
                features.update({"fast_hands", "second_story_work"})
                granted.add("fast_hands")
        elif name == "cleric":
            features.add("disciple_of_life")
            if "heavy" not in rpg["armor_proficiencies"]:
                rpg["armor_proficiencies"].append("heavy")
            if level >= 2:
                resource(actor, "channel_divinity", 1, "short")
                granted.update({"turn_undead", "preserve_life"})
        elif name == "wizard":
            granted.add("arcane_recovery")
            resource(actor, "arcane_recovery", 1, "day")
            if level >= 2:
                features.update({"evocation_savant", "sculpt_spells"})
    rpg["features"] = sorted(features)
    rpg["abilities"] = sorted(set(rpg["abilities"]) | {"ability." + key + "@1" for key in granted})
    caster_level = counts["cleric"] + counts["wizard"]
    for index, number in enumerate(SPELL_SLOTS[caster_level], 1):
        resource(actor, f"slot_{index}", number, "long")
    rpg["level"] = len(rpg["classes"])
    rpg["proficiency"] = proficiency(actor)


def spells_for(world, name, class_count, *, cantrips=False):
    highest = (class_count + 1) // 2
    return sorted(key for key, spec in world["definitions"].items()
                  if spec["type"] == "ability" and spec.get("spell") and name in spec["classes"]
                  and ((spec["level"] == 0) if cantrips else (0 < spec["level"] <= highest)))


def choose_class(world, aid, intent):
    actor = world["actors"][aid]
    rpg = actor["rpg"]
    name = intent.get("class")
    require(world["combat"] is None, "Finish the encounter before choosing a level.")
    require(name in CLASSES, "Choose Fighter, Rogue, Cleric, or Wizard.")
    total = len(rpg["classes"])
    require(total < 3, "This rules catalog supports character levels 1–3.")
    require(rpg["xp"] >= XP_THRESHOLDS[total], "Earn more experience before taking this level.")
    cls = CLASSES[name]
    first = not total
    entering = name not in rpg["classes"]
    if not first and entering:
        for existing in set(rpg["classes"]) | {name}:
            qualified = (max(actor["stats"]["str"], actor["stats"]["dex"]) >= 13 if existing == "fighter"
                         else actor["stats"][{"rogue": "dex", "cleric": "wis", "wizard": "int"}[existing]] >= 13)
            require(qualified, f"Multiclassing requires a qualifying score of 13 for {existing}.")
    next_level = class_level(actor, name) + 1
    if next_level >= cls["subclass_level"]:
        require(intent.get("subclass", cls["subclass"]) == cls["subclass"], "That subclass is not in the installed catalog.")
        rpg.setdefault("subclasses", {})[name] = cls["subclass"]
    rpg["classes"].append(name)
    rpg.setdefault("armor_proficiencies", [])
    rpg.setdefault("weapon_proficiencies", [])
    rpg.setdefault("tools", [])
    if entering:
        armors = cls["armor"] if first else [key for key in cls["armor"] if key != "heavy"] if name != "wizard" else []
        rpg["armor_proficiencies"] = sorted(set(rpg["armor_proficiencies"]) | set(armors))
        weapons = cls["weapons"] if first or name == "fighter" else []
        rpg["weapon_proficiencies"] = sorted(set(rpg["weapon_proficiencies"]) | set(weapons))
        if first:
            rpg["saves"] = cls["saves"][:]
        count = cls["skill_count"] if first else 1 if name == "rogue" else 0
        available = [skill for skill in cls["skills"] if skill not in rpg["skills"]]
        chosen = intent.get("skills", available[:count])
        require(isinstance(chosen, list) and len(set(chosen)) == len(chosen) == count and set(chosen) <= set(available),
                f"Choose {count} available {name} skills.")
        rpg["skills"] = sorted(set(rpg["skills"]) | set(chosen))
        if name == "rogue":
            rpg["tools"] = sorted(set(rpg["tools"]) | {"thieves_tools"})
            expertise = intent.get("expertise", rpg["skills"][:2])
            require(isinstance(expertise, list) and len(set(expertise)) == len(expertise) == 2
                    and set(expertise) <= set(rpg["skills"] + ["thieves_tools"]), "Choose two trained skills/tools for Expertise.")
            rpg["expertise"] = sorted(set(rpg["expertise"]) | set(expertise))
        if name == "fighter":
            style = intent.get("style", "defense")
            require(style in {"archery", "defense", "dueling", "two_weapon", "great_weapon", "protection"}, "Unknown fighting style.")
            rpg["style"] = style
    gain = max(1, (cls["hit_die"] if first else cls["hit_die"] // 2 + 1) + modifier(actor, "con"))
    # Retain an existing character's authored HP floor at its first class choice.
    if first:
        gain = max(0, gain - actor["max_hp"])
    actor["max_hp"] += gain
    actor["hp"] += gain
    derive(actor)
    if name in {"cleric", "wizard"}:
        rpg.setdefault("cantrips", {})
        rpg.setdefault("spellbook", [])
        rpg.setdefault("prepared_by_class", {})
        rpg["casting"] = cls["casting"]
        if entering:
            available = spells_for(world, name, next_level, cantrips=True)
            chosen = intent.get("cantrips", available[:3])
            require(isinstance(chosen, list) and len(set(chosen)) == len(chosen) <= 3 and len(chosen) == min(3, len(available))
                    and set(chosen) <= set(available), "Choose the supported cantrips for this class.")
            rpg["cantrips"][name] = chosen[:]
        if name == "wizard":
            available = [key for key in spells_for(world, name, next_level) if key not in rpg["spellbook"]]
            count = min(6 if entering else 2, len(available))
            learned = intent.get("spells", available[:count])
            require(isinstance(learned, list) and len(set(learned)) == len(learned) == count and set(learned) <= set(available),
                    f"Choose {count} new wizard spells for your spellbook.")
            rpg["spellbook"].extend(learned)
        available = spells_for(world, name, next_level)
        if name == "wizard":
            available = [key for key in available if key in rpg["spellbook"]]
        rpg["prepared_by_class"][name] = available[:max(1, modifier(actor, cls["casting"]) + next_level)]
    if first:
        starter_kit(world, aid, name)
    event = emit(world, "level", aid, text=f"{actor['name']} takes {name.title()} level {next_level} (character level {total + 1}).")
    rpg.setdefault("choices", []).append({"sequence": event["sequence"], "intent": deepcopy(intent)})
    return event


def prepared_abilities(world, aid):
    actor = world["actors"][aid]
    rpg = actor["rpg"]
    keys = set(rpg["abilities"])
    for value in rpg.get("cantrips", {}).values():
        keys.update(value)
    for value in rpg.get("prepared_by_class", {}).values():
        keys.update(value)
    cleric = class_level(actor, "cleric")
    if cleric:
        keys.update({"ability.bless@1", "ability.cure_wounds@1"})
    if cleric >= 3:
        keys.update({"ability.lesser_restoration@1", "ability.spiritual_weapon@1"})
    if rpg.get("spiritual_weapon", {}).get("ends_at", 0) > world["tick"]:
        keys.add("ability.spiritual_strike@1")
    return sorted(key for key in keys if key in world["definitions"])


def prepare(world, aid, intent):
    actor = world["actors"][aid]
    require(world["combat"] is None, "Prepare spells outside an encounter.")
    require(actor["rpg"].get("prepare_until", -1) >= world["tick"], "Complete a long rest before changing prepared spells.")
    name = intent.get("class")
    require(name in {"cleric", "wizard"} and class_level(actor, name), "Choose one of your spellcasting classes.")
    keys = intent.get("abilities")
    available = spells_for(world, name, class_level(actor, name))
    if name == "wizard":
        available = [key for key in available if key in actor["rpg"]["spellbook"]]
    limit = max(1, class_level(actor, name) + modifier(actor, CLASSES[name]["casting"]))
    require(isinstance(keys, list) and len(set(keys)) == len(keys) <= limit and set(keys) <= set(available), "Invalid prepared spell selection.")
    actor["rpg"].setdefault("prepared_by_class", {})[name] = keys[:]
    return emit(world, "prepare", aid, text=f"{actor['name']} prepares {len(keys)} {name} spells.")


def instantiate(world, key, place, owner=None):
    spec = definition(world, key)
    require(spec["type"] == "item", "Only item definitions create physical items.")
    iid = allocate_id(world, "item")
    instance = {"id": iid, "definition": key, "name": spec["name"], "kind": spec["kind"],
        "place": deepcopy(place), "owner": owner, "weight": spec["weight"], "condition": 100,
        "damage": int(spec["dice"].split("d")[1].split("+")[0]) if spec.get("dice") else 0}
    for value in ("uses", "charges", "fuel_ticks", "ink_gp", "spell"):
        if value in spec:
            instance[value] = spec[value]
    world["items"][iid] = instance
    from .migration import ensure_render_ids
    ensure_render_ids(world)
    if spec["kind"] == "container":
        world["fixtures"][iid] = {"id": iid, "name": spec["name"], "position": [0, 0], "item": iid, "open": True, "capacity": spec["capacity"]}
    return instance


def starter_kit(world, aid, name):
    kits = {"fighter": ["chain_mail", "shield", "longsword", "shortbow"],
            "rogue": ["leather", "shortsword", "dagger", "shortbow", "tools"],
            "cleric": ["chain_mail", "shield", "mace", "focus"],
            "wizard": ["quarterstaff", "focus", "spell_ink"]}
    actor = world["actors"][aid]
    for key in kits[name] + ["rope", "healers_kit", "paper", "ink"]:
        instance = instantiate(world, "itemdef." + key + "@1", {"carrier": aid}, aid)
        if instance["kind"] == "armor":
            actor["rpg"]["armor"] = instance["id"]
        elif instance["kind"] == "shield":
            actor["rpg"]["shield"] = instance["id"]
        elif instance["kind"] == "weapon" and not actor["equipped"]:
            actor["equipped"] = instance["id"]
    if name in {"fighter", "rogue"}:
        for _ in range(20):
            instantiate(world, "itemdef.arrows@1", {"carrier": aid}, aid)
    # Inventory weight is the existing compact load system, not pounds.
    actor["capacity"] = max(actor["capacity"], 30)


def armor_class(world, aid):
    from .minds import active_effects, has_condition
    actor = world["actors"][aid]
    rpg = actor["rpg"]
    armor = world["items"].get(rpg.get("armor"))
    spec = item_rules(world, armor) if armor and armor["place"].get("carrier") == aid else {}
    dex = modifier(actor, "dex")
    ac = spec.get("ac", 13 if has_condition(world, aid, "mage_armor") else 10) + min(dex, spec.get("dex_cap", dex))
    if rpg.get("shield") and world["items"][rpg["shield"]]["place"].get("carrier") == aid:
        ac += 2
    if spec and rpg.get("style") == "defense":
        ac += 1
    ac += passive_bonus(world, aid, "ac_bonus")
    if has_condition(world, aid, "shielded"):
        ac += 5
    return ac


def passive_bonus(world, aid, field):
    return sum(item_rules(world, world["items"][iid]).get(field, 0) for iid in world["actors"][aid]["rpg"]["attuned"]
               if iid in world["items"] and world["items"][iid]["place"].get("carrier") == aid)


def speed(world, aid):
    from .minds import has_condition
    actor = world["actors"][aid]
    if actor["hp"] <= 0 or any(has_condition(world, aid, key) for key in ("restrained", "stunned", "paralyzed", "unconscious")):
        return 0
    armor = world["items"].get(actor["rpg"].get("armor"))
    spec = item_rules(world, armor) if armor else {}
    return max(0, actor.get("speed", 6) - (2 if actor["stats"]["str"] < spec.get("strength", 0) else 0))


def award(world, recipients, amount, cause, reason):
    integer(amount, 1, 900, "experience award")
    require(isinstance(cause, str) and cause and cause not in world["awards"], "That cause already awarded experience, or is missing.")
    require(isinstance(reason, str) and 0 < len(reason) <= 800, "Explain the accomplishment.")
    require(isinstance(recipients, list) and 0 < len(set(recipients)) == len(recipients) <= 4
            and set(recipients) <= set(world["actors"]), "Choose known recipients for experience.")
    world["awards"][cause] = {"amount": amount, "recipients": recipients[:], "reason": reason, "tick": world["tick"]}
    for aid in recipients:
        world["actors"][aid]["rpg"]["xp"] += amount
        emit(world, "experience", aid, text=f"{world['actors'][aid]['name']} earns {amount} XP: {reason}")


def untrained_armor(world, aid):
    actor = world["actors"][aid]
    armor = world["items"].get(actor["rpg"].get("armor"))
    trained = actor["rpg"]["armor_proficiencies"]
    return bool(armor and item_rules(world, armor).get("category") not in trained
                or actor["rpg"].get("shield") and "shield" not in trained)


def casting_unavailable(world, aid, spec):
    from .minds import has_condition
    actor = world["actors"][aid]
    components = spec.get("components", [])
    if "v" in components and has_condition(world, aid, "silenced"):
        return "You cannot speak the spell's words."
    if untrained_armor(world, aid):
        return "You cannot cast in armor or a shield you are not proficient with."
    if set(components) & {"s", "m"} and actor["equipped"] and (actor["rpg"].get("shield") or actor["rpg"].get("offhand")):
        return "Free a hand for the spell's gestures or materials."
    if "m" in components and not any(item["place"].get("carrier") == aid and item["kind"] == "focus" for item in world["items"].values()):
        return "This spell requires a casting focus."
    return None


def finish_rest(world, aid, rest, intent):
    actor = world["actors"][aid]
    rpg = actor["rpg"]
    if rest == "short":
        spent = intent.get("hit_dice", [])
        require(isinstance(spent, list) and len(spent) <= 3, "Choose up to three hit dice.")
        for name in spent:
            require(name in CLASSES, "Unknown hit die class.")
            spend(actor, "hit_dice_" + name)
            rolled = dice(world, f"1d{CLASSES[name]['hit_die']}")
            healed = max(0, rolled["total"] + modifier(actor, "con"))
            actor["hp"] = min(actor["max_hp"], actor["hp"] + healed)
            emit(world, "recovery", aid, text=f"{actor['name']} spends a {name} hit die, recovering {healed} HP.", dice=rolled)
        rpg["short_rest_at"] = world["tick"]
    else:
        require(world["tick"] - rpg.get("long_rest_at", -14400) >= 14400, "A long rest can benefit you only once per day.")
        actor["hp"] = actor["max_hp"]
        actor["life"] = "alive"
        rpg["death_saves"] = {"success": 0, "failure": 0}
        rpg["long_rest_at"] = world["tick"]
        rpg["prepare_until"] = world["tick"] + 600
        remaining = max(1, len(rpg["classes"]) // 2)
        for name in rpg["classes"]:
            value = rpg["resources"]["hit_dice_" + name]
            if remaining and value["current"] < value["max"]:
                value["current"] += 1
                remaining -= 1
    for value in rpg["resources"].values():
        if value["recovery"] == "short" or rest == "long" and value["recovery"] == "long":
            value["current"] = value["max"]
    return emit(world, "rest_complete", aid, text=f"{actor['name']} completes a {rest} rest.")


def party_action(world, aid, intent):
    from .minds import can_identify, resolve_reference
    target = resolve_reference(world, aid, intent.get("target"))
    require(target in world["actors"] and target != PLAYER, "Choose a companion.")
    actor = world["actors"][target]
    party = world["party"]
    kind = intent["kind"]
    if kind == "recruit":
        require(world["combat"] is None, "Recruit companions outside combat.")
        require(target not in party["members"] and len(party["members"]) < party["limit"], "The party is full or already includes them.")
        require(can_identify(world, aid, target) and distance(world["actors"][aid]["position"], actor["position"]) <= 4, "Speak with that character nearby.")
        require(actor.get("join_offer_until", -1) >= world["tick"], "Ask this character whether they are willing to join first.")
        party["members"].append(target)
        actor["join_offer_until"] = -1
        actor["plan"] = None
    elif kind == "dismiss":
        require(target in party["members"], "That character is not a companion.")
        party["members"].remove(target)
        actor["orders"] = None
        actor["plan"] = None
    else:
        require(target in party["members"], "Give orders to a companion.")
        require(isinstance(intent.get("text"), str) and 0 < len(intent["text"]) <= 800, "Give a short request.")
        from .actions import apply_action
        _, spoken = apply_action(world, aid, {"kind": "speak", "target": target, "text": intent["text"], "channel": intent.get("channel", "speech")})
        require(target in spoken["perceptions"], "That companion did not receive the request.")
        actor["orders"] = {"text": intent["text"], "from": aid, "tick": world["tick"], "source_sequence": spoken["sequence"]}
    return emit(world, kind, aid, targets=[target], text=f"{world['actors'][aid]['name']} {'recruits' if kind == 'recruit' else 'dismisses' if kind == 'dismiss' else 'asks'} {actor['name']}" + (": " + intent["text"] if kind == "order" else "."))


def copy_spell(world, aid, intent, *, commit=False):
    actor = world["actors"][aid]
    book = world["items"].get(intent.get("item"))
    require(book and book["place"].get("carrier") == aid and book.get("spell"), "Carry a written spell source before copying it.")
    spec = definition(world, book["spell"])
    require(spec["id"] in spells_for(world, "wizard", class_level(actor, "wizard")), "You cannot yet prepare a wizard spell of this level.")
    require(spec["id"] not in actor["rpg"].get("spellbook", []), "That spell is already in your spellbook.")
    savant = "evocation_savant" in actor["rpg"]["features"] and spec.get("school") == "evocation"
    cost = (25 if savant else 50) * spec["level"]
    ticks = (600 if savant else 1200) * spec["level"]
    inks = [item for item in world["items"].values() if item["place"].get("carrier") == aid and item["kind"] == "spell_ink"]
    require(sum(item.get("ink_gp", 0) for item in inks) >= cost, f"Copying needs {cost} gp of arcane inks.")
    if commit:
        remaining = cost
        for item in inks:
            amount = min(remaining, item["ink_gp"])
            item["ink_gp"] -= amount
            remaining -= amount
            if not item["ink_gp"]:
                item["place"] = {"consumed": True}
        actor["rpg"].setdefault("spellbook", []).append(spec["id"])
        emit(world, "training", aid, text=f"{actor['name']} copies {spec['name']} into their spellbook, using {cost} gp of arcane inks.")
    return ticks
