"""DM authority: validated definitions, grounded grants, and declared rulings.

These operations are installed DM tools. They are not public player actions.
"""

from copy import deepcopy
import json
import re

from .abilities import MECHANICS
from .catalog import CLASSES, definition, item_rules
from .characters import award, instantiate, prepared_abilities
from .checks import SKILLS, STATS, check, integer, validate_dice
from .effects import apply_effect, validate_effect
from .migration import allocate_id
from .minds import can_identify, resolve_reference
from .perception import can_see, item_position, walkable
from .state import PLAYER, distance, emit, fingerprint, require


ABILITY_FIELDS = {"id", "type", "version", "name", "description", "level", "classes", "economy", "range", "target", "max_targets",
    "resolution", "effects", "spell", "components", "school", "concentration", "hostile", "resource", "mechanic", "save", "half_save",
    "radius", "upcast", "add_casting", "duration", "species", "repeat_save", "breaks_on"}
ITEM_FIELDS = {"id", "type", "version", "name", "description", "kind", "weight", "dice", "category", "weapon", "finesse", "light",
    "damage_type", "ranged", "range", "long_range", "ammo", "two_handed", "ac", "dex_cap", "stealth_disadvantage", "strength",
    "length", "fuel_ticks", "tool", "uses", "use", "capacity", "magic", "consumable", "effects", "bonus", "attunement", "ac_bonus",
    "save_bonus", "charges", "ability", "recharge", "ink_gp", "spell"}


def validate_definition(spec):
    require(isinstance(spec, dict) and spec.get("type") in {"ability", "item"}, "Choose an item or ability definition.")
    require(set(spec) <= (ABILITY_FIELDS if spec["type"] == "ability" else ITEM_FIELDS), "The content contains unsupported mechanics or fields.")
    require(isinstance(spec.get("name"), str) and 0 < len(spec["name"]) <= 100, "Content needs a short name.")
    require(isinstance(spec.get("description", ""), str) and len(spec.get("description", "")) <= 1600, "Content description is too long.")
    integer(spec.get("version", 1), 1, 1000, "content version")
    if spec["type"] == "ability":
        for key in ("level", "range", "max_targets", "effects", "economy", "target", "resolution", "spell", "components", "classes"):
            require(key in spec, f"An ability needs {key}.")
        integer(spec["level"], 0, 2, "spell level")
        integer(spec["range"], 0, 24, "ability range")
        integer(spec["max_targets"], 1, 12, "target limit")
        require(spec["economy"] in {"action", "bonus", "reaction", "free", "rest"}, "Unknown action economy.")
        require(spec["target"] in {"self", "creature", "object", "point", "area", "cone", "cube"}, "Unknown target mode.")
        require(spec["resolution"] in {"automatic", "attack", "save"}, "Unknown resolution mode.")
        if spec["resolution"] == "save":
            require(spec.get("save") in STATS, "Choose a saving throw stat.")
        if spec["target"] in {"area", "cone", "cube"}:
            integer(spec.get("radius"), 1, 6, "area size")
        require(isinstance(spec["components"], list) and set(spec["components"]) <= {"v", "s", "m"}, "Unknown spell components.")
        require(isinstance(spec["classes"], list) and set(spec["classes"]) <= set(CLASSES), "Unknown casting classes.")
        require(not spec.get("mechanic") or spec["mechanic"] in MECHANICS, "That ability mechanic needs an engine extension.")
        require(spec.get("repeat_save") is None or spec["repeat_save"] in STATS, "Unknown repeat saving throw.")
        require(spec.get("breaks_on") is None or spec["breaks_on"] == "attack_or_spell", "Unknown expiry trigger.")
        require(not spec.get("resource") or spec["resource"] in {"second_wind", "action_surge", "channel_divinity", "arcane_recovery"}, "Unknown resource cost.")
        require(spec["effects"] or spec.get("mechanic"), "An ability needs executable effects.")
        if spec.get("upcast"):
            validate_dice(spec["upcast"])
    else:
        require(spec.get("kind") in {"weapon", "armor", "shield", "ammunition", "rope", "lantern", "oil", "tools", "kit", "food", "paper", "ink", "spell_ink", "focus", "container", "potion", "wondrous", "wand", "trinket", "book"}, "Unknown item capability.")
        integer(spec.get("weight"), 0, 100, "item weight")
        if spec["kind"] == "weapon":
            validate_dice(spec.get("dice"))
            require(spec.get("category") in {"simple", "martial"} and isinstance(spec.get("weapon"), str), "Specify a weapon proficiency.")
        if spec["kind"] == "armor":
            require(spec.get("category") in {"light", "medium", "heavy"}, "Unknown armor category.")
            integer(spec.get("ac"), 10, 18, "armor class")
        for key, low, high in (("bonus", 0, 3), ("ac_bonus", 0, 3), ("save_bonus", 0, 3), ("charges", 1, 20), ("capacity", 1, 100), ("range", 1, 24), ("long_range", 1, 64), ("uses", 1, 100), ("fuel_ticks", 1, 14400)):
            if key in spec:
                integer(spec[key], low, high, key)
        require(not spec.get("recharge") or spec["recharge"] == "dawn", "Unknown item recharge rule.")
    effects = spec.get("effects", [])
    require(isinstance(effects, list) and len(effects) <= 8, "Content permits at most eight effects.")
    for effect in effects:
        validate_effect(effect)
    return deepcopy(spec)


def grounding(world, cause, reason):
    require(type(cause) is int and any(event["sequence"] == cause for event in world["events"]), "Cite a recorded world event as the acquisition or accomplishment.")
    event = next(event for event in world["events"] if event["sequence"] == cause)
    require(event["kind"] in {"quest_complete", "milestone", "discovery", "training", "encounter_end", "give", "read", "check", "ruling"}
            and event.get("success", True), "A claim or failed attempt is not an earned acquisition or accomplishment.")
    require(isinstance(reason, str) and 0 < len(reason) <= 800, "Record the in-world reason.")


def author(world, operation):
    require(isinstance(operation, dict), "A DM operation must be an object.")
    kind = operation.get("kind")
    reason = operation.get("reason", "")
    require(isinstance(reason, str) and 0 < len(reason) <= 800, "Record the DM's reason.")
    result = None
    if kind == "define":
        spec = validate_definition(operation.get("definition"))
        slug = operation.get("slug")
        require(isinstance(slug, str) and re.fullmatch(r"[a-z][a-z0-9_]{1,60}", slug), "Use a stable content slug.")
        prefix = "ability." if spec["type"] == "ability" else "itemdef."
        family = prefix + slug + "@"
        versions = [entry["version"] for key, entry in world["definitions"].items() if key.startswith(family)]
        spec["version"] = max(versions, default=0) + 1
        spec["id"] = family + str(spec["version"])
        if spec.get("ability"):
            require(definition(world, spec["ability"])["type"] == "ability", "The item ability is unavailable.")
        if spec.get("spell") and spec["type"] == "item":
            require(definition(world, spec["spell"]).get("spell"), "A spell source must reference an installed spell.")
        world["definitions"][spec["id"]] = spec
        world["content_revision"] += 1
        result = spec["id"]
    elif kind in {"place", "grant", "award"}:
        grounding(world, operation.get("cause"), reason)
        key = f"{kind}:{operation['cause']}:{operation.get('definition', '')}:{operation.get('actor', PLAYER)}"
        require(key not in world.setdefault("acquisitions", {}), "That acquisition has already been resolved.")
        if kind == "place":
            position = operation.get("position")
            require(isinstance(position, list) and len(position) == 2 and all(type(n) is int for n in position) and walkable(world, position), "Place the item at a valid world location.")
            result = instantiate(world, operation.get("definition"), {"ground": position}, operation.get("owner"))["id"]
        elif kind == "grant":
            aid = operation.get("actor", PLAYER)
            require(aid in world["actors"], "Choose an existing recipient.")
            spec = definition(world, operation.get("definition"))
            require(spec["type"] == "ability", "Grant an ability definition.")
            require(spec["id"] not in world["actors"][aid]["rpg"]["abilities"], "That character already knows this ability.")
            world["actors"][aid]["rpg"]["abilities"].append(spec["id"])
            result = spec["id"]
        else:
            award(world, operation.get("actors", world["party"]["members"]), operation.get("amount"), "event:" + str(operation["cause"]), reason)
        world["acquisitions"][key] = {"reason": reason, "source_revision": world["revision"], "cause": operation["cause"]}
    elif kind == "character":
        from .characters import choose_class
        aid, intent = operation.get("actor"), operation.get("intent", {})
        require(aid in world["party"]["members"] and isinstance(intent, dict), "Choose a party character and a supported character choice.")
        require(not world["combat"], "Make progression and preparation choices outside combat.")
        require(intent.get("kind") == "choose_class", "This operation supports earned class choices.")
        result = choose_class(world, aid, intent)["sequence"]
    elif kind == "schedule":
        from .schedules import install_schedule
        result = install_schedule(world, operation.get("schedule"))
    elif kind == "cancel_schedule":
        sid = operation.get("schedule")
        require(sid in world["schedules"], "Unknown schedule.")
        world["schedules"][sid]["remaining"] = 0
        world["consequences"] = [job for job in world["consequences"] if job["schedule"] != sid]
    elif kind == "value":
        aid = operation.get("actor")
        require(aid in world["actors"], "Choose an existing character.")
        value = operation.get("value", {})
        require(isinstance(value, dict) and set(value) <= {"name", "description", "event", "amount", "duration", "duty"}, "Unknown value reaction.")
        require(all(isinstance(value.get(key), str) and 0 < len(value[key]) <= 300 for key in ("name", "description", "event")), "A value needs a name, description and event reaction.")
        integer(value.get("amount"), -20, 20, "thought strength")
        integer(value.get("duration"), 1, 14400, "thought duration")
        integer(value.get("duty", 0), 0, 100, "duty priority")
        require(len(world["actors"][aid]["values"]) < 8, "At most eight approved values per character.")
        world["actors"][aid]["values"].append(deepcopy(value))
        world["actors"][aid]["duty"] = max(world["actors"][aid]["duty"], value.get("duty", 0))
    elif kind == "fixture":
        fixture = operation.get("fixture", {})
        require(isinstance(fixture, dict) and set(fixture) <= {"name", "position", "hp", "ac", "open", "offers", "capacity", "description"}, "Unsupported fixture properties.")
        require(isinstance(fixture.get("name"), str) and 0 < len(fixture["name"]) <= 100, "Name the fixture.")
        point = fixture.get("position")
        require(isinstance(point, list) and len(point) == 2 and all(type(n) is int for n in point) and walkable(world, point), "Choose a traversable fixture location.")
        if "hp" in fixture:
            integer(fixture["hp"], 1, 100, "object HP")
        if "ac" in fixture:
            integer(fixture["ac"], 5, 25, "object AC")
        result = allocate_id(world, "fixture")
        world["fixtures"][result] = {**deepcopy(fixture), "id": result}
    elif kind == "link":
        link = operation.get("link", {})
        require(isinstance(link, dict) and set(link) <= {"name", "from", "to", "open", "bidirectional", "key"}, "Unsupported connection fields.")
        require(isinstance(link.get("name"), str) and 0 < len(link["name"]) <= 100, "Name the connection.")
        for point in (link.get("from"), link.get("to")):
            require(isinstance(point, list) and len(point) == 2 and all(type(n) is int for n in point) and walkable(world, point), "Connections need two traversable endpoints.")
        result = allocate_id(world, "link")
        world["links"][result] = {**deepcopy(link), "id": result}
    else:
        require(False, "That DM operation is not implemented.")
    world.setdefault("authoring_log", []).append({"kind": kind, "reason": reason, "result": result, "source_revision": world["revision"], "tick": world["tick"]})
    text = "The DM records a world ruling."
    if kind == "place" and can_see(world, PLAYER, operation["position"]):
        text = f"{world['items'][result]['name']} is placed at {operation['position'][0]}, {operation['position'][1]}."
    elif kind == "grant" and operation.get("actor", PLAYER) == PLAYER:
        text = f"You learn {world['definitions'][result]['name']}."
    emit(world, "dm_authoring", PLAYER, text=text, channel="private", recipients=[PLAYER])
    return result


def ruling(world, aid, spec):
    """Validate an improvised attempt, record its stakes, then roll exactly once."""
    from .combat import pay
    require(isinstance(spec, dict), "A ruling must be an object.")
    allowed = {"name", "reason", "stakes", "capability", "targets", "range", "check", "success", "failure", "economy", "cost", "context", "preconditions", "basis"}
    require(set(spec) <= allowed, "Unsupported ruling fields.")
    for key in ("name", "reason", "stakes", "context"):
        require(isinstance(spec.get(key), str) and 0 < len(spec[key]) <= 800, f"Declare the ruling's {key}.")
    integer(spec.get("range", 1), 0, 24, "ruling range")
    actor = world["actors"][aid]
    capability = spec.get("capability", {})
    require(isinstance(capability, dict) and capability.get("kind") in {"body", "weapon", "item", "ability", "skill"}, "An attempt needs an existing capability.")
    kind = capability["kind"]
    ids = spec.get("targets", [])
    require(isinstance(ids, list) and 0 < len(ids) <= 8, "Choose up to eight ruling targets.")
    targets = [resolve_reference(world, aid, key) for key in ids]
    for target in targets:
        body = world["actors"].get(target)
        obj = world["items"].get(target)
        fixture = world["fixtures"].get(target) or world["map"]["doors"].get(target)
        point = body["position"] if body else item_position(world, obj) if obj else fixture["position"] if fixture else None
        require(point is not None and can_see(world, aid, point) and distance(actor["position"], point) <= spec.get("range", 1)
                and (not body or target == aid or can_identify(world, aid, target)), "A ruling target is unavailable or out of range.")
    effects = spec.get("success", []) + spec.get("failure", [])
    require(len(effects) <= 12, "A ruling permits twelve total consequences.")
    for effect in effects:
        validate_effect(effect)
        require(effect.get("target", targets[0]) in targets + [aid], "Ruling effects must address declared targets.")
    if kind in {"weapon", "item"}:
        item = world["items"].get(capability.get("id"))
        require(item and item["place"].get("carrier") == aid, "That capability is not in your inventory.")
        require(not any(effect["kind"] == "move" and effect.get("teleport") for effect in effects), "Improvised item movement cannot supply teleportation; activate an installed magical ability.")
        if kind == "weapon":
            require(actor["equipped"] == item["id"] and item["damage"] > 0, "Equip the required weapon first.")
            rules = item_rules(world, item)
            require(spec.get("range", 1) <= rules.get("range", 1), "The ruling exceeds the weapon's range.")
            if rules.get("ammo"):
                ammo = next((entry for entry in world["items"].values() if entry["place"].get("carrier") == aid and entry["kind"] == "ammunition"
                             and item_rules(world, entry).get("ammo") == rules["ammo"]), None)
                require(ammo is not None, "No ammunition remains for that attempt.")
            require(all(effect["kind"] in {"damage", "object_damage", "sound", "move"} for effect in effects), "A weapon cannot supply magical or mental effects.")
        else:
            rules = item_rules(world, item)
            allowed_kinds = {entry["kind"] for entry in rules.get("effects", [])} | {"sound", "move", "object_damage"}
            require(all(effect["kind"] in allowed_kinds for effect in effects), "That item has no capability for this effect.")
    elif kind == "ability":
        require(capability.get("id") in prepared_abilities(world, aid), "That ability is not available to you.")
        ability = definition(world, capability["id"])
        require(spec.get("range", 1) <= ability["range"], "The attempt exceeds the ability's range.")
        require(set(effect["kind"] for effect in effects) <= {effect["kind"] for effect in ability["effects"]}, "The attempt asks for effects beyond this ability.")
        if ability["level"]:
            require(spec.get("cost", {}).get("resource") == f"slot_{ability['level']}", "An improvised spell must pay its spell slot.")
    else:
        if kind == "skill":
            require(capability.get("id") in SKILLS, "Unknown skill.")
        require(all(effect["kind"] in {"sound", "move", "object_damage", "door", "belief", "relationship"} for effect in effects), "An ordinary action cannot supply this magical effect.")
        require(not any(effect["kind"] == "move" and effect.get("teleport") for effect in effects), "An ordinary action cannot teleport.")
    for condition in spec.get("preconditions", []):
        from .schedules import predicate, validate_predicate
        validate_predicate(condition)
        require(predicate(world, condition, {"source": aid, "event": {"actor": aid, "targets": targets}}), "A declared precondition is not satisfied.")
    # A context is a named obstacle/approach. Repeat attempts need a concrete new
    # capability/position/target change or a separately grounded DM ruling.
    if spec.get("basis") is not None:
        grounding(world, spec["basis"], spec["reason"])
    context_key = fingerprint({"actor": aid, "capability": capability, "targets": targets,
                               "position": actor["position"], "equipment": actor["equipped"], "basis": spec.get("basis")})
    require(context_key not in world["rulings"], "This attempt is already resolved. Change the circumstances before retrying.")
    declared = emit(world, "ruling", aid, targets=targets, text=spec["stakes"])
    pay(world, aid, spec.get("economy", "action"))
    if spec.get("cost"):
        from .characters import spend
        require(set(spec["cost"]) <= {"resource", "amount"}, "Unsupported ruling cost.")
        amount = integer(spec["cost"].get("amount", 1), 1, 3, "resource cost")
        spend(actor, spec["cost"].get("resource"), amount)
    if kind == "weapon" and rules.get("ammo"):
        ammo["place"] = {"consumed": True}
    checked = spec.get("check")
    result = None
    if checked:
        require(isinstance(checked, dict) and set(checked) <= {"stat", "skill", "difficulty", "advantage", "saving"}, "Unsupported check fields.")
        result = check(world, aid, **checked)
        emit(world, "check", aid, targets=targets, text=spec["name"], **result)
    accepted = result is None or result["success"]
    old_cause = world.get("_cause")
    world["_cause"] = declared["sequence"]
    try:
        for effect in spec.get("success" if accepted else "failure", []):
            apply_effect(world, aid, effect.get("target", targets[0]), effect, origin="ruling:" + context_key)
    finally:
        if old_cause is None:
            world.pop("_cause", None)
        else:
            world["_cause"] = old_cause
    world["rulings"][context_key] = {"definition": deepcopy(spec), "source_revision": world["revision"], "check": result,
                                    "success": accepted, "sequence": declared["sequence"]}
    return declared
