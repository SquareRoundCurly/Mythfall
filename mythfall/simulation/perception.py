"""Pathfinding and actor-limited observations of canonical state."""

from collections import deque
from copy import deepcopy
from contextvars import ContextVar
from functools import lru_cache, wraps

from .state import distance

_geometry = ContextVar("mythfall_geometry", default=None)


def geometry_scope(function):
    """Cache geometry for one synchronous resolver or projection call."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        if _geometry.get() is not None:
            return function(*args, **kwargs)
        token = _geometry.set({})
        try:
            return function(*args, **kwargs)
        finally:
            _geometry.reset(token)
    return wrapped


def blocked(world):
    cache = _geometry.get()
    # Doors can change during a turn; installed turn operations cannot edit walls.
    key = (id(world["map"]["walls"]), tuple((tuple(door["position"]), door["open"]) for door in world["map"]["doors"].values()))
    if cache is not None and key in cache:
        return cache[key]
    obstacles = frozenset(tuple(p) for p in world["map"]["walls"]) | frozenset(
        tuple(door["position"]) for door in world["map"]["doors"].values() if not door["open"]
    )
    if cache is not None:
        cache[key] = obstacles
    return obstacles


@lru_cache(maxsize=8192)
def line_clear(obstacles, start, destination):
    x0, y0 = start
    x1, y1 = destination
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    error = dx + dy
    while (x0, y0) != (x1, y1):
        twice = 2 * error
        if twice >= dy:
            error += dy
            x0 += sx
        if twice <= dx:
            error += dx
            y0 += sy
        if (x0, y0) in obstacles:
            return False
    return True


def walkable(world, point, obstacles=None):
    x, y = point
    return (0 <= x < world["map"]["width"] and 0 <= y < world["map"]["height"]
            and (x, y) not in (obstacles if obstacles is not None else blocked(world)))


def path_to(world, start, target, *, adjacent=False):
    obstacles = blocked(world)
    queue = deque([tuple(start)])
    previous = {tuple(start): None}
    target = tuple(target)
    while queue:
        current = queue.popleft()
        if current == target or (adjacent and distance(current, target) <= 1):
            path = []
            while previous[current] is not None:
                path.append(list(current))
                current = previous[current]
            return list(reversed(path))
        x, y = current
        for neighbor in ((x, y - 1), (x - 1, y), (x + 1, y), (x, y + 1)):
            if neighbor not in previous and walkable(world, neighbor, obstacles):
                previous[neighbor] = current
                queue.append(neighbor)
    return None


def can_see(world, actor_id, position):
    from .minds import has_condition, sense_range

    observer = world["actors"][actor_id]
    if observer["hp"] <= 0 or observer["activity"] == "sleeping" or has_condition(world, actor_id, "blinded"):
        return False
    x0, y0 = observer["position"]
    x1, y1 = position
    if distance((x0, y0), position) > sense_range(world, actor_id, "vision"):
        return False
    if position in world["map"].get("dark_tiles", []) and distance((x0, y0), position) > 1:
        illuminated = False
        for item in list(world["items"].values()) + [entry for entry in world["fixtures"].values() if not entry.get("item")]:
            light = item.get("light", {})
            radius = 6 if item.get("lit") else light.get("radius", 0) if light.get("ends_at", 0) > world["tick"] else 0
            point = item_position(world, item) if "place" in item else item["position"]
            if point is not None and radius and distance(point, position) <= radius and line_clear(blocked(world), tuple(point), tuple(position)):
                illuminated = True
                break
        if not illuminated:
            return False
    return line_clear(blocked(world), (x0, y0), (x1, y1))


def item_position(world, item):
    place = item["place"]
    if "ground" in place:
        return place["ground"]
    if "carrier" in place:
        return world["actors"][place["carrier"]]["position"]
    if "container" in place:
        fixture = world["fixtures"][place["container"]]
        return item_position(world, world["items"][fixture["item"]]) if fixture.get("item") else fixture["position"]
    return None


def known_destination(world, aid, target):
    """Resolve travel from the actor's observations or remembered location."""
    from .minds import can_identify, resolve_reference
    from .state import require
    target = resolve_reference(world, aid, target)
    known = world["actors"][aid]["known"].get(target, {})
    point = known.get("position") or known.get("place", {}).get("ground")
    if target in world["map"]["places"]:
        return world["map"]["places"][target]["center"][:]
    if target in world["actors"] and can_identify(world, aid, target):
        point = world["actors"][target]["position"]
    elif target in world["items"]:
        if target in {item["id"] for item in observe(world, aid)["items"]}:
            point = item_position(world, world["items"][target])
    elif target in world["fixtures"]:
        fixture = world["fixtures"][target]
        physical = item_position(world, world["items"][fixture["item"]]) if fixture.get("item") else fixture["position"]
        if physical is not None and can_see(world, aid, physical):
            point = physical
    require(point is not None, "That destination has not been observed.")
    return point[:]


@geometry_scope
def observe(world, actor_id):
    from .minds import appearance, can_identify, private_sheet, reference

    actor = world["actors"][actor_id]
    actors = []
    for aid, other in sorted(world["actors"].items()):
        if aid == actor_id or can_identify(world, actor_id, aid):
            entry = {k: deepcopy(other[k]) for k in ("id", "name", "position", "color", "hp", "max_hp", "activity", "equipped")}
            entry.update(id=reference(world, actor_id, aid), name=appearance(world, actor_id, aid)[1])
            entry.update(life=other["life"], can_recruit=other.get("join_offer_until", -1) >= world["tick"])
            if entry["id"] != aid:
                entry.update(equipped=None, color="#8c9299")
            actors.append(entry)
    items = []
    for item in world["items"].values():
        place = item["place"]
        visible_ground = "ground" in place and can_see(world, actor_id, place["ground"])
        carried = place.get("carrier") == actor_id
        visible_equipped = any(a["equipped"] == item["id"] for a in actors)
        container = world["fixtures"].get(place.get("container"))
        contained = container and container.get("open") and item_position(world, item) is not None and distance(actor["position"], item_position(world, item)) <= 1
        remains = place.get("carrier") in world["actors"] and world["actors"][place["carrier"]]["hp"] == 0 and distance(actor["position"], world["actors"][place["carrier"]]["position"]) <= 1
        if visible_ground or carried or visible_equipped or contained or remains:
            perceived = deepcopy(item)
            from .minds import has_condition
            from .catalog import item_rules
            point = item_position(world, item)
            if point is not None and distance(actor["position"], point) <= 6 and has_condition(world, actor_id, "detect_magic"):
                perceived["magical_aura"] = bool(item_rules(world, item).get("magic") or item.get("light", {}).get("ends_at", 0) > world["tick"])
            if not carried and item["owner"] != actor_id:
                perceived["owner"] = actor["known"].get(item["id"], {}).get("owner")
            if "carrier" in perceived["place"]:
                perceived["place"]["carrier"] = reference(world, actor_id, perceived["place"]["carrier"])
            if perceived.get("message"):
                message = perceived["message"]
                perceived["message"] = {"sealed": message["sealed"], "read": actor_id in message["read_by"]}
                if actor_id in message["read_by"]:
                    perceived["message"].update(text=message["text"], language=message["language"])
            items.append(perceived)
    from .combat import public_combat
    fixtures = {}
    visible_items = {item["id"] for item in items}
    for fid, fixture in world["fixtures"].items():
        if fixture.get("item") and fixture["item"] not in visible_items:
            continue
        point = item_position(world, world["items"][fixture["item"]]) if fixture.get("item") else fixture["position"]
        if point is not None and can_see(world, actor_id, point):
            fixtures[fid] = {key: deepcopy(value) for key, value in fixture.items() if key in {"id", "name", "description", "open", "locked", "offers", "hp", "ac", "capacity"}}
            fixtures[fid]["position"] = point[:]
            if "open" in fixture:
                fixtures[fid].setdefault("capacity", 100)
    return {"tick": world["tick"], "revision": world["revision"], "sequence": world["sequence"],
            "self": private_sheet(world, actor_id), "actors": actors, "items": items,
            "doors": {did: deepcopy(door) for did, door in world["map"]["doors"].items()
                      if can_see(world, actor_id, door["position"])},
            "events": deepcopy(actor["memories"][-200:]), "combat": public_combat(world, actor_id),
            "fixtures": fixtures,
            "links": {lid: deepcopy(link) for lid, link in world["links"].items() if can_see(world, actor_id, link["from"])}}
