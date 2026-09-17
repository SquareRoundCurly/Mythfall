"""Verify the published module carries the simulation and immutable game art."""

import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile


def verify(directory):
    wheels = list(Path(directory).glob("mythfall-*.whl"))
    assert len(wheels) == 1, "Expected exactly one Mythfall wheel"
    with ZipFile(wheels[0]) as wheel:
        names = set(wheel.namelist())
        assert not any("__pycache__" in name or name.endswith(".pyc") for name in names), "Wheel must not include local bytecode"
        for name in ("world_agent.py", "world_runtime.py", "world_models.py", "game_chat.py",
                     "simulation/battlemap.py", "simulation/store.py", "rpg_prompts.py",
                     "simulation/migration.py", "simulation/abilities.py", "simulation/catalog.py",
                     "simulation/characters.py", "simulation/combat.py", "simulation/effects.py",
                     "simulation/minds.py", "simulation/authoring.py", "simulation/schedules.py",
                     "simulation/adventure.py", "simulation/sheets.py", "seed/RULES.md",
                     "seed/README.md", "seed/assets/battlemap-v1/prompts.json"):
            assert f"mythfall/{name}" in names, f"Missing packaged file: {name}"
        assert not any(name.startswith(("tests/", "evaluation/")) for name in names)
        pngs = [name for name in names if name.startswith("mythfall/seed/assets/") and name.endswith(".png")]
        assert len(pngs) == 8, "Expected three battle-map sheets and five portraits"
        for name in pngs:
            data = wheel.read(name)
            assert data.startswith(b"\x89PNG\r\n\x1a\n"), f"Invalid PNG: {name}"
            path = Path(name)
            source = Path(__file__).parents[1] / path
            assert hashlib.sha256(data).digest() == hashlib.sha256(source.read_bytes()).digest(), name
        # A reader must be able to inspect the exact authoring prompts after install.
        assert json.loads(wheel.read("mythfall/seed/assets/battlemap-v1/prompts.json"))
        assert b"Creative Commons Attribution 4.0" in wheel.read("mythfall/seed/RULES.md")
    print("Mythfall wheel includes RPG rules and attribution, simulation, exact art bytes, and prompts.")


if __name__ == "__main__":
    verify(sys.argv[1])
