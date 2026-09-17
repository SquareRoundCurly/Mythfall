"""Shared, validated effects for player and NPC intents."""

from copy import deepcopy

from .perception import can_see, item_position, walkable
from .state import PLAYER, distance, emit, require, roll
from .minds import can_hear, can_identify, has_condition, resolve_reference, relationship_change


def inventory(world, aid):
    return [item for item in world["items"].values() if item["place"].get("carrier") == aid]


def apply_action(world, aid, intent, *, _paid=False):
    require(aid in world["actors"], "Unknown actor.")
    actor = world["actors"][aid]
    require(actor["hp"] > 0, "An unconscious character cannot act.")
    require(isinstance(intent, dict), "An action must be an object.")
    kind = intent.get("kind")
    require(kind in {"move", "take", "drop", "equip", "unequip", "give", "use", "speak", "inspect", "check", "attack", "rest", "work", "idle",
                    "ability", "choose_class", "prepare", "recruit", "dismiss", "order", "dodge", "dash", "disengage", "hide", "stand", "help", "offhand", "climb",
                    "write", "read", "put", "loot", "eat_remains", "traverse", "attune", "refuel"},
            "Unknown world action.")
    target = resolve_reference(world, aid, intent.get("target"))
    text = ""
    cost = 1
    actor["activity"] = "idle"
    from . import combat
    from .characters import choose_class, prepare, party_action, speed
    from .catalog import item_rules
    if kind == "choose_class":
        return 0, choose_class(world, aid, intent)
    if kind == "prepare":
        event = prepare(world, aid, intent)
        return max(1, sum(world["definitions"][key]["level"] for key in intent["abilities"])) * 10, event
    if kind in {"recruit", "dismiss", "order"}:
        return 0, party_action(world, aid, intent)
    if kind == "ability":
        from .abilities import activate
        cost = 0 if world["definitions"].get(intent.get("ability"), {}).get("economy") == "rest" else 1
        return cost, activate(world, aid, intent)
    if kind in {"attack", "offhand"}:
        return 1, combat.weapon_attack(world, aid, target, nonlethal=bool(intent.get("nonlethal")), offhand=kind == "offhand")
    require(not combat.incapacitated(world, aid) or kind == "inspect", "An incapacitated character cannot act.")
    if kind in {"dash", "disengage", "hide"}:
        from .abilities import resolve_special
        combat.pay(world, aid, "action")
        resolve_special(world, aid, {"mechanic": kind, "id": "action." + kind}, intent, [], None, 0, "wis")
        return 1, emit(world, kind, aid, text=f"{actor['name']} uses {kind}.")
    if kind == "dodge":
        from .effects import apply_effect
        combat.pay(world, aid, "action")
        apply_effect(world, aid, aid, {"kind": "condition", "condition": "guarded", "duration": 2}, origin="action.dodge")
        if world["combat"]:
            for effect in world["effects"].values():
                if effect.get("origin") == "action.dodge" and effect["target"] == aid:
                    effect.update(until_turn_actor=aid, until_turn_serial=world["combat"]["turn_serial"])
        return 1, emit(world, kind, aid, text=f"{actor['name']} takes the Dodge action.")
    if kind == "stand":
        from .effects import apply_effect
        require(has_condition(world, aid, "prone"), "You are already standing.")
        if world["combat"]:
            budget = combat.turn_budget(world, aid)
            require(world["combat"]["awaiting"] == aid and budget["movement"] >= speed(world, aid) // 2, "Standing uses half your speed.")
            budget["movement"] -= speed(world, aid) // 2
        return 1, apply_effect(world, aid, aid, {"kind": "remove_condition", "condition": "prone"})
    if kind == "help":
        require(target in world["actors"] and distance(actor["position"], world["actors"][target]["position"]) <= 1, "Help a creature within reach.")
        combat.pay(world, aid, "action")
        world["actors"][target]["rpg"]["help"] = {"source": aid, "ends_at": world["tick"] + 2, "skill": intent.get("skill")}
        return 1, emit(world, kind, aid, targets=[target], text=f"{actor['name']} helps {world['actors'][target]['name']}.")
    if kind in {"write", "read", "put", "loot", "eat_remains", "traverse", "attune", "refuel"}:
        from .objects import interact
        return interact(world, aid, {**intent, "target": target})
    if world["combat"]:
        require(world["combat"]["awaiting"] == aid and world["combat"]["pending"] is None, "Wait for your turn.")
        if kind not in {"move", "inspect", "climb"}:
            economy = "speech" if kind == "speak" else "interaction" if kind in {"take", "drop", "equip", "unequip", "give"} else "action"
            if economy == "interaction" and combat.turn_budget(world, aid)["interaction"] == 0:
                economy = "action"
            if not _paid:
                combat.pay(world, aid, economy)

    if kind in {"move", "climb"}:
        position = intent.get("position")
        require(isinstance(position, list) and len(position) == 2
                and all(isinstance(v, int) and not isinstance(v, bool) for v in position), "Use an integer map position.")
        require(distance(actor["position"], position) == 1, "Movement is one adjacent tile per action.")
        require(walkable(world, position), "That path is blocked.")
        require(speed(world, aid) > 0, "You cannot move in your current condition.")
        if world["combat"]:
            budget = combat.turn_budget(world, aid)
            movement = 2 if has_condition(world, aid, "prone") or kind == "climb" and "second_story_work" not in actor["rpg"]["features"] else 1
            require(budget["movement"] >= movement, "No movement remains this turn.")
            budget["movement"] -= movement
            reaction_event = combat.movement_reactions(world, aid, position)
            if reaction_event:
                return 0, reaction_event
        actor["position"] = position[:]
        actor["activity"] = "walking"
        text = f"{actor['name']} moves."
    elif kind == "unequip":
        slot = intent.get("slot", "weapon")
        require(slot in {"weapon", "armor", "shield", "offhand"}, "Unknown equipment slot.")
        if slot == "weapon":
            actor["equipped"] = None
        else:
            require(slot != "armor" or world["combat"] is None, "Remove armor outside combat.")
            actor["rpg"][slot] = None
        text = f"{actor['name']} stows their {slot}."
    elif kind in {"take", "drop", "equip", "give"}:
        require(target in world["items"], "That item does not exist.")
        item = world["items"][target]
        carried = item["place"].get("carrier") == aid
        if kind == "take":
            position = item_position(world, item)
            require("ground" in item["place"] or "container" in item["place"], "That item is already carried or consumed.")
            require(position is not None and can_see(world, aid, position)
                    and distance(actor["position"], position) <= 1, "Move within reach of the item first.")
            if "container" in item["place"]:
                require(world["fixtures"][item["place"]["container"]]["open"], "The container is closed.")
            from .objects import load, item_load
            container = world["items"].get(item["place"].get("container"))
            already_weighed = container and container["place"].get("carrier") == aid and not item_rules(world, container).get("magic")
            require(load(world, aid) + (0 if already_weighed else item_load(world, item)) <= actor["capacity"], "You cannot carry that much.")
            item["place"] = {"carrier": aid}
            text = f"{actor['name']} picks up {item['name']}."
        else:
            require(carried, "That item is not in your inventory.")
            if kind == "drop":
                item["place"] = {"ground": actor["position"][:]}
                text = f"{actor['name']} leaves {item['name']} on the ground."
            elif kind == "equip":
                spec = item_rules(world, item)
                slot = intent.get("slot")
                if item["kind"] == "armor":
                    require(world["combat"] is None, "Don armor outside combat.")
                    actor["rpg"]["armor"] = target
                    cost = {"light": 10, "medium": 50, "heavy": 100}[spec["category"]]
                elif item["kind"] == "shield":
                    require(not actor["rpg"].get("offhand"), "Stow the offhand weapon first.")
                    actor["rpg"]["shield"] = target
                else:
                    require(item["damage"] > 0, "That item cannot be equipped in a weapon slot.")
                    if slot == "offhand":
                        require(not actor["rpg"].get("shield") and target != actor["equipped"], "The offhand must be free.")
                        actor["rpg"]["offhand"] = target
                    else:
                        actor["equipped"] = target
                text = f"{actor['name']} equips {item['name']}."
            elif kind == "give":
                recipient_id = resolve_reference(world, aid, intent.get("recipient"))
                require(recipient_id in world["actors"] and recipient_id != aid, "Choose another character.")
                recipient = world["actors"][recipient_id]
                require(recipient["hp"] > 0 and distance(actor["position"], recipient["position"]) <= 1,
                        "The recipient must be conscious and within reach.")
                from .objects import load, item_load
                require(load(world, recipient_id) + item_load(world, item) <= recipient["capacity"],
                        "The recipient cannot carry that much.")
                item["place"] = {"carrier": recipient_id}
                item["owner"] = recipient_id
                text = f"{actor['name']} gives {item['name']} to {recipient['name']}."
            if kind != "equip" and actor["equipped"] == target:
                actor["equipped"] = None
            if kind != "equip":
                for slot in ("armor", "shield", "offhand"):
                    if actor["rpg"].get(slot) == target:
                        actor["rpg"][slot] = None
        event = emit(world, kind, aid, targets=[target], text=text,
                     item_place=deepcopy(item["place"]), owner=item["owner"])
        if kind == "give":
            relationship_change(world, recipient_id, aid, 1, event["sequence"])
        if kind == "take" and item["owner"] in world["actors"] and item["owner"] != aid:
            owner = world["actors"][item["owner"]]
            if item["owner"] in event["witnesses"]:
                relationship_change(world, owner["id"], aid, -1, event["sequence"])
                if owner.get("defend_property") and not world["combat"]:
                    allies = [key for key, body in world["actors"].items() if key != owner["id"] and body.get("faction") == owner.get("faction")
                              and body["hp"] > 0 and can_identify(world, key, aid)]
                    combat.start(world, aid, [owner["id"], *allies])
        return cost, event
    elif kind == "use":
        if target in world["fixtures"]:
            fixture = world["fixtures"][target]
            require("open" in fixture, "Describe how you want to interact with this fixture to the DM.")
            point = item_position(world, world["items"][target]) if fixture.get("item") else fixture["position"]
            require(point is not None and can_see(world, aid, point) and distance(actor["position"], point) <= 1, "Reach the fixture first.")
            require(not fixture.get("locked"), "The fixture is locked.")
            fixture["open"] = intent.get("open", not fixture["open"])
            require(type(fixture["open"]) is bool, "Choose an open or closed state.")
            text = f"{actor['name']} {'opens' if fixture['open'] else 'closes'} {fixture['name']}."
        elif target in world["map"]["doors"]:
            door = world["map"]["doors"][target]
            require(distance(actor["position"], door["position"]) <= 1, "Move beside the door first.")
            require(not door["locked"], "The door is locked.")
            desired = intent.get("open", not door["open"])
            require(isinstance(desired, bool), "Door state must be true or false.")
            require(desired or not any(a["position"] == door["position"] for a in world["actors"].values()),
                    "Someone is standing in the doorway.")
            door["open"] = desired
            text = f"{actor['name']} {'opens' if desired else 'closes'} {door['name']}."
        else:
            require(target in world["items"], "That item does not exist.")
            item = world["items"][target]
            require(item["place"].get("carrier") == aid, "That item is not carried by you.")
            if item["kind"] not in {"food", "lantern"}:
                from .objects import use_item
                return 1, use_item(world, aid, item, intent)
            if item["kind"] == "food":
                item["place"] = {"consumed": True}
                actor["hunger"] = max(0, actor["hunger"] - 5000)
                actor["needs_warning"] = False
                text = f"{actor['name']} eats {item['name']}."
            else:
                require(item.get("fuel_ticks", 3600) > 0, "The lantern needs oil.")
                item.setdefault("fuel_ticks", 3600)
                item["lit"] = not item.get("lit", False)
                text = f"{actor['name']} {'lights' if item['lit'] else 'extinguishes'} {item['name']}."
    elif kind == "speak":
        require(isinstance(intent.get("text"), str) and 0 < len(intent["text"].strip()) <= 1200, "Speech must be between 1 and 1200 characters.")
        channel = intent.get("channel", "speech")
        require(channel in {"speech", "whisper", "telepathy"}, "Unsupported speech channel.")
        language = intent.get("language", "common")
        require(language in actor.get("languages", ["common"]), "You do not speak that language.")
        if channel == "telepathy":
            replying = target in world["actors"] and has_condition(world, target, "telepathy") and any(
                memory.get("kind") == "speech" and memory.get("channel") == "telepathy" and memory.get("actor") == target
                for memory in actor["memories"][-20:])
            require(has_condition(world, aid, "telepathy") or replying, "You have no active telepathic connection.")
        if target:
            require(target in world["actors"], "Unknown conversation target.")
            require(can_identify(world, aid, target) or target in actor["known"], "You do not know that recipient.")
            require((channel == "telepathy" and distance(actor["position"], world["actors"][target]["position"]) <= 12)
                    or (channel != "telepathy" and can_hear(world, target, actor["position"], 1 if channel == "whisper" else 4)),
                    "That character cannot receive your words from here.")
        require(channel != "telepathy" or target is not None, "Telepathy needs a recipient.")
        text = intent["text"].strip()
        return cost, emit(world, "speech", aid, targets=[target] if target else [], text=text,
                          channel=channel, language=language, recipients=[target] if target else [])
    elif kind in {"inspect", "check"}:
        if target in world["actors"]:
            require(can_identify(world, aid, target), "You cannot perceive that character.")
            position = world["actors"][target]["position"]
        elif target in world["items"]:
            position = item_position(world, world["items"][target])
            require(world["items"][target]["place"].get("carrier") in (None, aid)
                    or world["actors"][world["items"][target]["place"]["carrier"]]["equipped"] == target,
                    "You cannot inspect another character's hidden inventory.")
        elif target in world["fixtures"]:
            position = world["fixtures"][target]["position"]
        else:
            require(False, "Choose an observable character, item, or fixture.")
        require(position is not None and can_see(world, aid, position), "You cannot see that target.")
        if kind == "check":
            from .checks import check
            key = f"{target}:{intent.get('skill') or intent.get('stat', 'wis')}"
            require(key not in actor["rpg"].setdefault("examined", {}), "You have already examined this. Describe a changed approach to the DM.")
            result = check(world, aid, skill=intent.get("skill"), stat=intent.get("stat"), difficulty=world["fixtures"].get(target, {}).get("clue_dc", 12))
            actor["rpg"]["examined"][key] = {"tick": world["tick"], "result": result}
            event = emit(world, kind, aid, targets=[target], text=f"{actor['name']} makes a {(intent.get('skill') or result['stat']).replace('_', ' ')} check.",
                         **result)
            fixture = world["fixtures"].get(target, {})
            if result["success"] and fixture.get("clue"):
                actor["known"].setdefault(target, {}).update(clue=fixture["clue"], tick=world["tick"], source_sequence=event["sequence"])
                emit(world, "discovery", aid, targets=[target], text=fixture["clue"], channel="private", recipients=[aid])
            if result["success"] and intent.get("skill") == "insight" and target in world["actors"]:
                from .minds import mood
                feeling = mood(world, world["actors"][target])
                emit(world, "insight", aid, text="Their manner seems " + ("troubled." if feeling < -10 else "at ease." if feeling > 10 else "composed; their deeper motives remain uncertain."), channel="private", recipients=[aid])
            return cost, event
        cost = 0
        text = world["fixtures"].get(target, {}).get("description", f"{actor['name']} looks closely.")
    elif kind == "rest":
        actor["activity"] = "sleeping"
        return 1, None
    elif kind in {"work", "idle"}:
        actor["activity"] = "working" if kind == "work" else "idle"
        return 10, None
    return cost, emit(world, kind, aid, targets=[target] if target else [], text=text)
