"""Pure projections of player-visible world state into an Atlas scene and UI."""

from copy import deepcopy
import json
from pathlib import Path
import shutil

from .battlemap import ACTOR_TILES, ART_PATH, ITEM_TILES, ensure_art, sprite
from .perception import observe
from .state import PLAYER, STEP_SECONDS
from .minds import reference


def color(hex_color, alpha=1):
    value = hex_color.lstrip("#")
    return [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)] + [alpha]


def quad(eid, name, x, y, width, height, tint, *, z=0, shape="quad", visible=True):
    return {"id": eid, "name": name, "canvas": {"bitmask": 2},
            "transform": {"position": [x - 32, 23 - y, z], "scale": [width, height, 1]},
            "drawable": {"shape": shape, "color": color(tint), "visible": visible}}


def dynamic_entities(world):
    view = observe(world, PLAYER)
    visible_actors = {a["id"]: a for a in view["actors"]}
    visible_items = {i["id"] for i in view["items"] if "ground" in i["place"]}
    player = world["actors"][PLAYER]
    px, py = player["position"]
    entities = [{"id": 0, "name": "Mythfall camera", "canvas": {"bitmask": 2},
                 "transform": {"position": [px - 29, 23 - py, 100]},
                 "camera": {"projection": "orthographic", "target": [px - 29, 23 - py, 0],
                            "width": 36, "height": 28, "near": 0.1, "far": 200}}]
    for n, (aid, actor) in enumerate(sorted(world["actors"].items())):
        observed = visible_actors.get(reference(world, PLAYER, aid))
        visible = observed is not None
        x, y = actor["position"] if visible else [0, 0]
        base = world["render_slots"]["actors"][aid]
        name = observed["name"] if visible else "Unseen character"
        slug = aid.removeprefix("char.") if observed and observed["id"] == aid else "player"
        tint = observed["color"] if visible else "#8c9299"
        # A thin token ring keeps silhouettes readable against textured terrain.
        entities.extend([
            quad(base, f"{name} marker", x, y, 1.65, 1.65, tint, z=2, shape="circle", visible=visible),
            quad(base + 2, f"{name} marker inset", x, y, 1.49, 1.49, "#354139", z=2.1, shape="circle", visible=visible),
            quad(base + 5, f"{name} health", x, y + 1, max(.01, .9 * actor["hp"] / actor["max_hp"]) if visible else .01, .10,
                 "#b2c484" if actor["hp"] > actor["max_hp"] / 2 else "#c97063", z=5, visible=visible),
        ])
        # Atlas loads model resources with the scene. Preload each available
        # appearance and switch masks, never a live entity's model source. All
        # actors get the same neutral variant set, including unseen actors.
        for offset, variant in zip((1, 3, 4, 6, 7, 8), ACTOR_TILES):
            entities.append(sprite(base + offset, name, x, y, 1.95, 1.95,
                                   f"actor-{variant}", z=3,
                                   visible=visible and variant == (slug if slug in ACTOR_TILES else "player")))
    for n, (iid, item) in enumerate(sorted(world["items"].items())):
        visible = iid in visible_items
        x, y = item["place"].get("ground", [0, 0]) if visible else [0, 0]
        base = world["render_slots"]["items"][iid]
        if iid in {"item.sword", "item.lantern", "item.book", "item.survey_ledger"} and item["kind"] in ITEM_TILES:
            entities.append(sprite(base, item["name"] if visible else "Unseen item", x + .7, y + .6, 1.3, 1.3,
                                   f"prop-{item['kind']}", z=3.1, visible=visible))
        else:
            weapon = item["damage"] > 0
            entities.extend([
                quad(base, item["name"] if visible else "Unseen item", x + .7, y + .6,
                     .14 if weapon else .40, .85 if weapon else .45, "#a78b62", z=3.1, visible=visible),
                quad(base + 1, "Item detail", x + .7, y + .83, .48 if weapon else .2, .12, "#ad824c", z=3.2, visible=visible),
            ])
    for n, (did, door) in enumerate(sorted(world["map"]["doors"].items())):
        visible_door = view["doors"].get(did)
        x, y = door["position"]
        entities.append(sprite(30000 + n, door["name"], x, y, 1.25, 1.25, "prop-door", z=1.8,
                               visible=visible_door is not None and not visible_door["open"]))
    return entities


def scene(world):
    return {"systems": [
        {"Atlas::Systems::GraphicsSystem": {"context": 2, "pipeline": "atlas:unlit"}},
        {"Atlas::Systems::PbrSystem": {"context": 2, "pipeline": "atlas:pbr-lite"}},
    ], "entities": [{"id": 1, "name": "Emberwick battle map", "canvas": {"bitmask": 2},
                     "transform": {"position": [0, 0, 0]},
                     "model": {"source": f"{ART_PATH}/village.gltf"}}] + dynamic_entities(world)}


def packet(world):
    from ..game_chat import chat_view
    from .sheets import party_sheets
    from .catalog import CLASSES

    view = observe(world, PLAYER)
    seconds = world["tick"] * STEP_SECONDS
    view.update(day=seconds // 86400 + 1, time=f"{seconds // 3600 % 24:02d}:{seconds // 60 % 60:02d}",
                pending=deepcopy(world["pending"]), pending_consequences=len(world["consequences"]), combat=view.get("combat"),
                places=deepcopy(world["map"]["places"]), width=world["map"]["width"], height=world["map"]["height"])
    if view["combat"] and "opponent" in view["combat"]:
        view["combat"]["opponent"] = reference(world, PLAYER, view["combat"]["opponent"])
    view["characters"] = party_sheets(world)
    view["party"] = {"members": [reference(world, PLAYER, aid) for aid in world["party"]["members"]], "limit": world["party"]["limit"]}
    view["classes"] = deepcopy(CLASSES)
    view["ability_names"] = {key: spec["name"] for key, spec in world["definitions"].items() if spec["type"] == "ability"}
    view["quests"] = [{key: deepcopy(quest[key]) for key in ("id", "name", "description", "status", "objective") if key in quest}
                      for quest in world["quests"].values() if quest.get("visible", True)]
    if world["combat"]:
        view["combat"]["needs_npc"] = (world["combat"].get("pending") or {}).get("reactor", world["combat"]["awaiting"]) != PLAYER
    return {"status": "ready", "world": view, "render": dynamic_entities(world), "chat": chat_view(world)}


def write_project(workspace, world):
    workspace = Path(workspace)
    ensure_art(workspace, world)
    path = workspace / "scene" / "mythfall.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = workspace / "game.json"
    if manifest.exists():
        old = json.loads(manifest.read_text())
        if old.get("scene") != "scene/mythfall.json":
            backup = workspace / "state" / "legacy-game.json"
            backup.parent.mkdir(parents=True, exist_ok=True)
            if not backup.exists():
                shutil.copy2(manifest, backup)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(scene(world), separators=(",", ":")) + "\n")
    temporary.replace(path)
    manifest.write_text(json.dumps({"version": 1, "scene": "scene/mythfall.json"}) + "\n")
