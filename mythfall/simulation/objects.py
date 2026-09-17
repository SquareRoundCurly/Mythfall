"""Ordinary equipment, private physical messages, remains and connections."""

from copy import deepcopy

from .catalog import item_rules
from .checks import check, dice
from .effects import apply_effect
from .minds import can_identify, resolve_reference
from .perception import can_see, item_position, walkable
from .state import distance, emit, require


def carried(world, aid, kind=None):
    return [item for item in world["items"].values() if item["place"].get("carrier") == aid and (kind is None or item["kind"] == kind)]


def load(world, aid):
    return sum(item_load(world, item) for item in carried(world, aid))


def item_load(world, item):
    """Ordinary portable containers carry the weight of their contents."""
    weight = item["weight"]
    if item["kind"] == "container" and not item_rules(world, item).get("magic"):
        weight += sum(child["weight"] for child in world["items"].values()
                      if child["place"].get("container") == item["id"])
    return weight


def can_reach_item(world, aid, item):
    point = item_position(world, item)
    return point is not None and (item["place"].get("carrier") == aid or "carrier" not in item["place"])
    # Range and visibility are checked by the action that uses this predicate.


def use_item(world, aid, item, intent):
    event = emit(world, "use", aid, targets=[item["id"]], text=f"{world['actors'][aid]['name']} uses {item['name']}.")
    previous = world.get("_cause")
    world["_cause"] = event["sequence"]
    try:
        _use_item(world, aid, item, intent)
    finally:
        if previous is None:
            world.pop("_cause", None)
        else:
            world["_cause"] = previous
    return event


def _use_item(world, aid, item, intent):
    spec = item_rules(world, item)
    recipient = resolve_reference(world, aid, intent.get("recipient", aid)) if item["kind"] != "tools" else aid
    require(recipient in world["actors"] and distance(world["actors"][aid]["position"], world["actors"][recipient]["position"]) <= 1,
            "Use the item on yourself or a creature within reach.")
    if spec.get("effects"):
        for effect in spec["effects"]:
            apply_effect(world, aid, recipient, effect, origin=item["id"])
        if spec.get("consumable"):
            item["place"] = {"consumed": True}
    elif spec.get("ability"):
        from .abilities import activate
        require(item.get("charges", 0) > 0, "The item has no charges remaining.")
        activate(world, aid, {**intent, "ability": spec["ability"]}, item=item, paid=True)
        item["charges"] -= 1
    elif spec.get("use") == "stabilize":
        require(world["actors"][recipient]["life"] == "unconscious", "That creature does not need stabilizing.")
        require(item.get("uses", 0) > 0, "The healer's kit is empty.")
        item["uses"] -= 1
        duration = dice(world, "1d4")["total"] * 600
        apply_effect(world, aid, recipient, {"kind": "condition", "condition": "stable", "duration": duration})
        world["actors"][recipient]["rpg"]["death_saves"] = {"success": 0, "failure": 0}
    elif item["kind"] == "tools":
        target = intent.get("object") or intent.get("recipient")
        require(target in world["map"]["doors"], "Choose a nearby locked door as the object.")
        door = world["map"]["doors"][target]
        require(door["locked"] and distance(world["actors"][aid]["position"], door["position"]) <= 1, "Choose a locked door within reach.")
        require(spec["tool"] in world["actors"][aid]["rpg"]["tools"], "This lock requires proficiency with thieves' tools.")
        key = f"lock:{target}:{door.get('lock_revision', 0)}"
        require(key not in world["actors"][aid]["rpg"].setdefault("examined", {}), "This lock defeated that approach. Describe a changed approach to the DM.")
        result = check(world, aid, stat="dex", tool=spec["tool"], difficulty=door.get("dc", 12))
        world["actors"][aid]["rpg"]["examined"][key] = result
        if result["success"]:
            door["locked"] = False
        emit(world, "check", aid, targets=[target], text="An attempt to pick the lock.", **result)
    else:
        require(False, "Describe the intended use to the DM; this item has no direct activation.")


def interact(world, aid, intent):
    from .combat import pay
    actor = world["actors"][aid]
    kind, target = intent["kind"], intent.get("target")
    cost = 1
    if kind == "traverse":
        link = world["links"].get(target)
        require(link and link.get("open", True), "That connection is unavailable.")
        source, destination = link["from"], link["to"]
        if link.get("bidirectional") and distance(actor["position"], destination) <= 1:
            source, destination = destination, source
        require(distance(actor["position"], source) <= 1 and can_see(world, aid, source), "Reach the connection first.")
        require(not link.get("key") or any(item["id"] == link["key"] or item.get("definition") == link["key"] for item in carried(world, aid)), "The connection requires its key.")
        require(walkable(world, destination), "The connection's destination is blocked.")
        pay(world, aid, "action")
        actor["position"] = destination[:]
        return cost, emit(world, "move", aid, targets=[target], position=destination, text=f"{actor['name']} traverses {link['name']}.")
    if kind == "eat_remains":
        body = world["actors"].get(target)
        require("remains" in actor["diet"] and body and body["life"] == "dead" and body.get("remains")
                and not body["remains"]["consumed"] and distance(actor["position"], body["position"]) <= 1,
                "No edible remains are within reach.")
        pay(world, aid, "action")
        body["remains"]["consumed"] = True
        apply_effect(world, aid, aid, {"kind": "need", "need": "hunger", "amount": -body["remains"]["nutrition"]})
        return cost, emit(world, "feed", aid, targets=[target], text=f"{actor['name']} feeds on remains.")
    if kind == "loot":
        body = world["actors"].get(target)
        require(body and body["hp"] == 0 and distance(actor["position"], body["position"]) <= 1, "Reach an incapacitated creature first.")
        iid = intent.get("item")
        item = world["items"].get(iid)
        require(item and item["place"].get("carrier") == target, "That possession is unavailable.")
        require(load(world, aid) + item_load(world, item) <= actor["capacity"], "You cannot carry that much.")
        pay(world, aid, "action")
        item["place"] = {"carrier": aid}
        if body["equipped"] == iid:
            body["equipped"] = None
        for slot in ("armor", "shield", "offhand"):
            if body["rpg"].get(slot) == iid:
                body["rpg"][slot] = None
        return cost, emit(world, "take", aid, targets=[iid], text=f"{actor['name']} takes {item['name']} from the fallen creature.", item_place=deepcopy(item["place"]), owner=item["owner"])
    require(target in world["items"], "Choose a physical item.")
    item = world["items"][target]
    require(item["place"].get("carrier") == aid, "That item must be in your inventory.")
    spec = item_rules(world, item)
    if kind == "write":
        require(item["kind"] == "paper" and not item.get("message"), "Choose unused parchment.")
        require(isinstance(intent.get("text"), str) and 0 < len(intent["text"]) <= 1600, "Write between 1 and 1600 characters.")
        language = intent.get("language", "common")
        require(language in actor["languages"], "You cannot write that language.")
        ink = next((value for value in carried(world, aid, "ink") if value.get("uses", 0) > 0), None)
        require(ink, "Writing requires ink and a quill.")
        pay(world, aid, "action")
        ink["uses"] -= 1
        item["name"] = "Sealed letter"
        item["message"] = {"text": intent["text"], "language": language, "author": aid, "sealed": True,
                           "read_by": [aid], "written_at": world["tick"]}
        return 10, emit(world, "write", aid, targets=[target], text=f"{actor['name']} writes and seals a letter.")
    if kind == "read":
        message = item.get("message")
        require(message, "This item has no written message.")
        require(not message["sealed"] or intent.get("open") is True, "Open the sealed letter before reading it.")
        pay(world, aid, "action")
        message["sealed"] = False
        understood = message["language"] in actor["languages"]
        if understood and aid not in message["read_by"]:
            message["read_by"].append(aid)
        event = emit(world, "read", aid, targets=[target], text=message["text"] if understood else "The letter is written in an unfamiliar language.",
                     channel="private", recipients=[aid], provenance="testimony")
        return cost, event
    if kind == "put":
        container = intent.get("recipient")
        fixture = world["fixtures"].get(container)
        require(fixture and fixture.get("open"), "Choose an open container.")
        point = item_position(world, world["items"][container]) if container in world["items"] else fixture["position"]
        require(point is not None and distance(actor["position"], point) <= 1 and can_see(world, aid, point), "The container is out of reach.")
        require(item["kind"] != "container", "Nested portable containers are not supported in this catalog.")
        contained = sum(other["weight"] for other in world["items"].values() if other["place"].get("container") == container)
        require(contained + item["weight"] <= fixture.get("capacity", 100), "The container is full.")
        pay(world, aid, "action")
        item["place"] = {"container": container}
        if actor["equipped"] == target:
            actor["equipped"] = None
        for slot in ("armor", "shield", "offhand"):
            if actor["rpg"].get(slot) == target:
                actor["rpg"][slot] = None
        return cost, emit(world, "put", aid, targets=[target], text=f"{actor['name']} puts {item['name']} into {fixture['name']}.", item_place=deepcopy(item["place"]))
    if kind == "attune":
        require(world["combat"] is None and actor["rpg"].get("short_rest_at", -1) == world["tick"], "Attune at the end of a short rest.")
        require(spec.get("attunement"), "This item does not require attunement.")
        require(target not in actor["rpg"]["attuned"] and len(actor["rpg"]["attuned"]) < 3, "There are no free attunement slots, or the item is already attuned.")
        require(not any(target in body["rpg"]["attuned"] for other, body in world["actors"].items() if other != aid), "The item is attuned to someone else.")
        actor["rpg"]["attuned"].append(target)
        return 0, emit(world, "attune", aid, targets=[target], text=f"{actor['name']} attunes to {item['name']}.")
    if kind == "refuel":
        require(item["kind"] == "lantern", "Choose a lantern.")
        oil = next(iter(carried(world, aid, "oil")), None)
        require(oil, "A flask of oil is required.")
        pay(world, aid, "action")
        oil["place"] = {"consumed": True}
        item["fuel_ticks"] = 3600
        return cost, emit(world, "refuel", aid, targets=[target], text=f"{actor['name']} refuels the lantern.")
    require(False, "Unsupported object interaction.")


def tick_objects(world):
    dawn = world["tick"] % 14400 == 3600
    for item in world["items"].values():
        if item.get("lit"):
            item["fuel_ticks"] = max(0, item.get("fuel_ticks", 3600) - 1)
            if item["fuel_ticks"] == 0:
                item["lit"] = False
        if dawn and item_rules(world, item).get("recharge") == "dawn":
            spec = item_rules(world, item)
            from .checks import dice
            item["charges"] = min(spec["charges"], item.get("charges", 0) + dice(world, "1d3")["total"])
    for actor in world["actors"].values():
        if world["tick"] % 14400 == 0 and "arcane_recovery" in actor["rpg"]["resources"]:
            actor["rpg"]["resources"]["arcane_recovery"]["current"] = 1
