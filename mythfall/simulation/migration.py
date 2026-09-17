"""Idempotent, deterministic evolution of saved worlds; never rebuild a save."""

from copy import deepcopy


WORLD_VERSION = 2


def upgrade_world(saved):
    if saved.get("version") not in (1, WORLD_VERSION):
        raise ValueError("Unsupported world version.")
    world = deepcopy(saved)
    world["version"] = WORLD_VERSION
    defaults = {"effects": {}, "schedules": {}, "consequences": [], "definitions": {},
                "rulings": {}, "quests": {}, "awards": {}, "links": {}, "zones": {},
                "party": {"leader": "char.player", "members": ["char.player"], "limit": 4},
                "content_revision": 0, "next_identity": 1}
    for key, value in defaults.items():
        world.setdefault(key, value)
    from .catalog import starting_catalog, CATALOG_VERSION
    for key, value in starting_catalog().items():
        world["definitions"].setdefault(key, value)
    world.setdefault("catalog_version", CATALOG_VERSION)
    for aid, actor in world["actors"].items():
        actor.setdefault("life", "alive" if actor["hp"] > 0 else "unconscious")
        actor.setdefault("species", "humanoid")
        actor.setdefault("diet", ["food"])
        actor.setdefault("languages", ["common"])
        actor.setdefault("senses", {"vision": 12, "hearing": 8})
        actor.setdefault("mind_revision", 0)
        actor.setdefault("beliefs", [])
        actor.setdefault("thoughts", [])
        actor.setdefault("values", [])
        actor.setdefault("attention", [])
        actor.setdefault("suppressed_events", [])
        actor.setdefault("references", {})
        actor.setdefault("duty", 0)
        actor.setdefault("orders", None)
        actor.setdefault("rpg", {"classes": [], "xp": 0, "skills": [], "expertise": [],
                                  "abilities": [], "prepared": [], "resources": {},
                                  "armor": None, "shield": None, "attuned": [],
                                  "death_saves": {"success": 0, "failure": 0}})
        for key, value in {"armor_proficiencies": [], "weapon_proficiencies": [], "saves": [],
                           "tools": [], "features": [], "subclasses": {}, "choices": []}.items():
            actor["rpg"].setdefault(key, value)
        # Old saves already contain witnessed memories. Preserve their content;
        # retain their provenance so later mind changes can invalidate them.
        for memory in actor["memories"]:
            memory.setdefault("source", "observed")
            memory.setdefault("confidence", "certain")
        actor.setdefault("known", {})
    combat = world.get("combat")
    if combat and "participants" not in combat:
        members = ["char.player", combat["opponent"]]
        world["combat"] = {"id": "encounter.legacy", "participants": [{"id": aid, "side": "party" if aid == "char.player" else "hostile", "initiative": 0, "die": 0} for aid in members],
            "turn": 0, "round": max(1, combat.get("round", 1)), "turn_serial": 1, "started_at": combat.get("started_at", world["tick"]),
            "awaiting": "char.player", "pending": None, "economy": {aid: {"action": 1 if aid == "char.player" else 0, "bonus": 1 if aid == "char.player" else 0,
                "reaction": 1, "movement": 6 if aid == "char.player" else 0, "interaction": 1, "speech": 1, "cast_bonus": False, "cast_levelled": False} for aid in members}}
    elif combat:
        for budget in combat["economy"].values():
            budget.setdefault("cast_bonus", False)
            budget.setdefault("cast_levelled", False)
    ensure_render_ids(world)
    return world


def ensure_render_ids(world):
    """Allocate once at mutation/migration boundaries; pure views never allocate.

    Keep the legacy IDs on first migration. Added inventory must not renumber
    an existing model, and these presentation IDs carry no actor names.
    """
    slots = world.setdefault("render_slots", {})
    for kind, base, stride in (("actors", 10000, 10), ("items", 20000, 5)):
        if kind not in slots:
            slots[kind] = {key: base + n * stride for n, key in enumerate(sorted(world[kind]))}
        next_id = max(slots[kind].values(), default=base - stride) + stride
        for key in sorted(world[kind]):
            if key not in slots[kind]:
                if kind == "items" and 30000 <= next_id < 100000:
                    next_id = 100000
                slots[kind][key] = next_id
                next_id += stride


def allocate_id(world, prefix):
    value = world["next_identity"]
    world["next_identity"] += 1
    return f"{prefix}.{value}"
