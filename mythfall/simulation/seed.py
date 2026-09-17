"""A compact village built from the existing Mythfall cast and locations."""

from pathlib import Path

import yaml

from .state import PLAYER, TICKS_PER_HOUR

LOCATION_PREFIX = "locations/lowmere/"
PLACES = [
    ("square", "Emberwick Square", "emberwick/village_square.md", [24, 24], [17, 17, 15, 14], None),
    ("inn", "Stonebridge Inn", "emberwick/stonebridge_inn/common_room.md", [42, 23], [35, 17, 14, 12], [35, 23]),
    ("hall", "Reeve's Hall", "emberwick/reeves_hall/office.md", [24, 7], [18, 2, 12, 10], [24, 11]),
    ("shrine", "Blackfen Shrine", "emberwick/blackfen_shrine/nave.md", [24, 37], [18, 32, 12, 11], [24, 32]),
    ("road", "Bramble Road", "bramble_road/old_milestone.md", [9, 24], [2, 18, 13, 12], None),
    ("watch", "Crowglass Watch", "crowglass_watch/ground_floor.md", [6, 7], [1, 2, 11, 10], [6, 11]),
    ("mine", "Crowglass Mine", "crowglass_mine/entrance.md", [56, 8], [51, 3, 12, 10], None),
    ("office", "Foreman's Office", "crowglass_mine/foremans_office.md", [56, 22], [51, 17, 12, 10], [56, 17]),
    ("gallery", "Flooded Gallery", "crowglass_mine/flooded_gallery.md", [56, 37], [51, 32, 12, 11], [56, 32]),
]
CAST = [
    ("old_nessa", "Old Nessa", [21, 24], [21, 6], "herbalist", "safekeep", "#b593da"),
    ("tommen_ash", "Tommen Ash", [42, 23], [44, 20], "innkeeper", "return", "#d49b5e"),
    ("mara_vell", "Mara Vell", [24, 7], [26, 6], "reeve", "safekeep", "#719eb8"),
    ("ellis_crow", "Ellis Crow", [24, 37], [22, 39], "scholar", "study", "#73b5a2"),
    ("brakka", "Brakka", [9, 24], [6, 7], "toll keeper", "keep", "#c46c65"),
]


def read_frontmatter(path):
    if not path.exists():
        return {}, ""
    text = path.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        try:
            _, metadata, body = text.split("---", 2)
            return yaml.safe_load(metadata) or {}, body.strip()
        except (ValueError, yaml.YAMLError):
            pass
    return {}, text


def actor(aid, name, position, home, role, interest, color, source, description):
    hp = source.get("hp") or {}
    maximum = max(1, int(hp.get("max", 16)))
    return {"id": aid, "name": source.get("name", name), "position": position[:],
            "home": home[:], "work": position[:], "role": role, "interest": interest,
            "color": color, "hp": max(0, min(maximum, int(hp.get("current", maximum)))), "max_hp": maximum,
            "stats": source.get("stats") or {"str": 12, "dex": 12, "con": 12, "int": 12, "wis": 12, "cha": 12},
            "hunger": 2000, "fatigue": 1500, "capacity": 12, "equipped": None,
            "ready_at": 8 * TICKS_PER_HOUR, "activity": "idle", "plan": None,
            "memories": [], "relationships": {}, "known": {}, "considered": {},
            "goals": source.get("goals", []), "lore": source.get("knowledge", []),
            "description": description, "needs_warning": False}


def new_world(workspace=None, *, seed=1741):
    seed_path = Path(__file__).parents[1] / "seed"
    source_path = Path(workspace) if workspace else seed_path
    world = {"version": 1, "revision": 0, "tick": 8 * TICKS_PER_HOUR,
             "rng": seed & 0xFFFFFFFF, "sequence": 0, "events": [], "receipts": {},
             "actors": {}, "items": {}, "fixtures": {}, "pending": None, "combat": None,
             "decisions": [], "map": {"width": 64, "height": 46, "places": {}, "walls": [], "doors": {}}}
    for key, name, suffix, center, bounds, door in PLACES:
        path = LOCATION_PREFIX + suffix
        world["map"]["places"][key] = {"id": key, "name": name, "path": path,
                                         "center": center, "bounds": bounds}
        if door:
            x, y, width, height = bounds
            walls = {(xx, yy) for xx in range(x, x + width) for yy in range(y, y + height)
                     if xx in (x, x + width - 1) or yy in (y, y + height - 1)}
            walls.discard(tuple(door))
            world["map"]["walls"].extend([list(point) for point in sorted(walls)])
            world["map"]["doors"][f"door.{key}"] = {"position": door, "open": True, "locked": False,
                                                       "name": f"{name} door"}
    for slug, name, position, home, role, interest, color in CAST:
        metadata, description = read_frontmatter(source_path / "characters" / f"{slug}.md")
        if not metadata:
            metadata, description = read_frontmatter(seed_path / "characters" / f"{slug}.md")
        aid = f"char.{slug}"
        world["actors"][aid] = actor(aid, name, position, home, role, interest, color, metadata, description)
    metadata, description = read_frontmatter(source_path / "characters" / "player.md")
    starting_place = next((p for p in world["map"]["places"].values() if p["path"] == metadata.get("location")),
                          world["map"]["places"]["square"])
    world["actors"][PLAYER] = actor(PLAYER, "Traveler", starting_place["center"], starting_place["center"],
                                    "adventurer", "none", "#edce81", metadata, description)
    add_item(world, "item.sword", "Iron sword", "sword", {"carrier": PLAYER}, PLAYER, weight=3, damage=6)
    add_item(world, "item.lantern", "Brass lantern", "lantern", {"carrier": PLAYER}, PLAYER, weight=1)
    add_item(world, "item.charm", "Copper charm", "trinket", {"carrier": "char.old_nessa"}, "char.old_nessa")
    add_item(world, "item.book", "Archive notebook", "book", {"carrier": "char.ellis_crow"}, "char.ellis_crow")
    add_item(world, "item.cudgel", "Oak cudgel", "weapon", {"carrier": "char.brakka"}, "char.brakka", damage=4)
    world["actors"]["char.brakka"]["equipped"] = "item.cudgel"
    for aid in world["actors"]:
        for n in range(3):
            add_item(world, f"food.{aid}.{n}", "Bread and apple", "food", {"carrier": aid}, aid)
    world["fixtures"]["chest.inn"] = {"id": "chest.inn", "name": "Inn pantry", "position": [39, 25], "open": True, "offers": ["food"]}
    for n in range(20):
        add_item(world, f"pantry.food.{n}", "Bread and apple", "food", {"container": "chest.inn"}, "char.tommen_ash")
    from .migration import upgrade_world
    return upgrade_world(world)


def add_item(world, iid, name, kind, place, owner=None, *, weight=1, damage=0):
    world["items"][iid] = {"id": iid, "name": name, "kind": kind, "place": place,
                           "owner": owner, "weight": weight, "damage": damage, "condition": 100}
