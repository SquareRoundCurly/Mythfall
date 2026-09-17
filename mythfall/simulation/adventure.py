"""A small authored adventure evaluated through reusable objective predicates."""

from .characters import award, choose_class, instantiate
from .migration import upgrade_world
from .seed import actor
from .state import PLAYER, emit

VERSION = 1


def install(world):
    if world.get("adventure_version") == VERSION:
        return world
    world = upgrade_world(world)
    world["adventure_version"] = VERSION
    world["adventure"] = {
        "name": "The Crowglass Ledger",
        "premise": "The village needs the mine's survey ledger before deciding whether to reopen the flooded gallery.",
        "dm_notes": "Mara wants the original survey ledger. Ellis can interpret the survey marks and may volunteer as a companion. "
                    "Two displaced watchkeepers hold the office as security for unpaid wages. They are not monsters: the reeve's written guarantee "
                    "or a credible negotiated solution can persuade them to release the ledger. They guard their chest, eat, listen and follow routines. "
                    "Stealth, a distraction, waiting for their rounds, careful persuasion or combat are viable approaches. "
                    "Do not award the ledger without moving the actual item. Do not claim wages paid without an actual recorded settlement. "
                    "Failed persuasion can lead to terms, preparation or retreat. Killing is not a quest requirement.",
    }
    world["fixtures"].setdefault("fixture.survey_marker", {"id": "fixture.survey_marker", "name": "Survey marker",
        "position": [55, 9], "description": "Old survey marks are cut into the lintel. A newer arrow points toward the foreman's office.",
        "clue": "The original mine survey was locked away in the foreman's office. A narrow drainage walk approaches its eastern side.", "clue_dc": 10})
    for aid, name, point in (("char.tovin_reed", "Tovin Reed", [55, 21]), ("char.kestrel_wren", "Kestrel Wren", [57, 23])):
        if aid not in world["actors"]:
            world["actors"][aid] = actor(aid, name, point, point, "displaced watchkeeper", "return", "#ac806e",
                {"hp": {"current": 11, "max": 11}, "stats": {"str": 12, "dex": 12, "con": 10, "int": 10, "wis": 12, "cha": 10},
                 "goals": ["Get a credible settlement of the watchkeepers' unpaid wages", "Keep the survey ledger safe until an agreement"],
                 "knowledge": ["Mara Vell can guarantee the outstanding wages in writing. The ledger belongs to the village."]},
                "A wary former watchkeeper, tired of broken promises. Avoids unnecessary killing.")
    world = upgrade_world(world)
    for aid in ("char.tovin_reed", "char.kestrel_wren"):
        body = world["actors"][aid]
        body.update(faction="watchkeepers", defend_property=True, duty=45)
        if not body["rpg"]["classes"]:
            choose_class(world, aid, {"class": "fighter", "style": "defense"})
        body["rpg"]["armor"] = None
        body["rpg"]["shield"] = None
    ellis = world["actors"]["char.ellis_crow"]
    if not ellis["rpg"]["classes"]:
        choose_class(world, ellis["id"], {"class": "cleric"})
        ellis["equipped"] = None
        ellis["rpg"]["prepared_by_class"]["cleric"] = ["ability.healing_word@1", "ability.sanctuary@1"]
    ellis["goals"] = list(ellis["goals"]) + ["Help a credible adventurer recover the mine survey; consider accompanying them if asked."]
    ellis["values"].append({"name": "Care for the living", "description": "Values aid to the injured.", "event": "heal", "amount": 4, "duration": 600})
    world["fixtures"].setdefault("chest.survey", {"id": "chest.survey", "name": "Survey chest", "position": [57, 21], "open": False,
        "locked": False, "hp": 12, "ac": 12, "description": "A sturdy chest under the watchkeepers' care.", "owner": "char.tovin_reed"})
    if "item.survey_ledger" not in world["items"]:
        world["items"]["item.survey_ledger"] = {"id": "item.survey_ledger", "name": "Crowglass survey ledger", "kind": "book", "weight": 1,
            "damage": 0, "condition": 100, "owner": "char.tovin_reed", "place": {"container": "chest.survey"},
            "message": {"text": "The gallery sluice was obstructed before the flood. The survey records prove that reopening without inspection is unsafe.",
                        "language": "common", "author": "char.mara_vell", "sealed": False, "read_by": [], "written_at": 0}}
    for aid in ("char.tovin_reed", "char.kestrel_wren"):
        world["actors"][aid]["known"]["item.survey_ledger"] = {"name": "Crowglass survey ledger", "position": [57, 21],
            "container": "chest.survey", "owner": "char.tovin_reed", "tick": world["tick"], "source": "personal knowledge"}
    world["quests"].setdefault("quest.survey_lead", {"id": "quest.survey_lead", "name": "Read the old survey marks", "status": "active", "visible": True,
        "description": "Old Nessa mentions survey marks near the Crowglass Mine entrance. A trained eye might learn where the records went.",
        "objective": "Inspect and investigate the survey marker near the mine entrance.",
        "conditions": [{"kind": "known", "actor": PLAYER, "target": "fixture.survey_marker", "field": "clue"}], "xp": 300})
    world["quests"].setdefault("quest.survey_return", {"id": "quest.survey_return", "name": "The Crowglass Ledger", "status": "active", "visible": True,
        "description": "Mara Vell needs the original mine survey. The foreman's office is occupied by former watchkeepers with an unpaid claim.",
        "objective": "Recover the actual ledger and give it to Mara at the Reeve's Hall. The method is yours to choose.",
        "conditions": [{"kind": "carried", "actor": "char.mara_vell", "target": "item.survey_ledger"}], "xp": 600})
    # Two ordinary patrol jobs. They use the same plans as NPC decisions and are
    # interrupted by combat, changed needs or an invalid route.
    from .schedules import install_schedule
    for aid, point, offset in (("char.tovin_reed", [55, 18], 20), ("char.kestrel_wren", [58, 25], 50)):
        install_schedule(world, {"name": "Watchkeeper's round", "source": aid, "actor": aid,
            "trigger": {"kind": "interval", "every": 100, "at": world["tick"] + offset},
            "actions": [{"kind": "travel", "position": point}, {"kind": "work"}, {"kind": "work"}, {"kind": "work"}],
            "conditions": [{"kind": "life", "actor": aid, "value": "alive"}]})
    from .migration import ensure_render_ids
    ensure_render_ids(world)
    return world


def objective_met(world, condition):
    kind = condition["kind"]
    if kind == "known":
        return bool(world["actors"][condition["actor"]]["known"].get(condition["target"], {}).get(condition["field"]))
    if kind == "carried":
        return world["items"].get(condition["target"], {}).get("place", {}).get("carrier") == condition["actor"]
    if kind == "life":
        return world["actors"].get(condition["actor"], {}).get("life") == condition["value"]
    if kind == "open":
        return world["fixtures"].get(condition["target"], {}).get("open") is condition["value"]
    return False


def evaluate(world):
    for quest in world["quests"].values():
        if quest["status"] == "active" and quest.get("conditions") and all(objective_met(world, condition) for condition in quest["conditions"]):
            quest.update(status="complete", completed_at=world["tick"])
            event = emit(world, "quest_complete", PLAYER, text=f"Completed: {quest['name']}.")
            if quest.get("xp"):
                award(world, world["party"]["members"], quest["xp"], "quest:" + quest["id"], "Completed " + quest["name"])
            quest["completion_event"] = event["sequence"]
