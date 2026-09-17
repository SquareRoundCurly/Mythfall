"""Local acceptance host using Mythfall's installed action and observation hooks."""

import json
import hashlib
import logging
import os
from pathlib import Path
import shutil

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from RealmEngine.modules import ModuleActionContext, ModuleSessionContext
from mythfall import MythfallModule, SEED_PATH
from mythfall.simulation.presentation import write_project
from mythfall.simulation.store import WorldStore

WORKSPACE = Path(os.environ["MYTHFALL_EVALUATION_WORKSPACE"]).resolve()
WORKSPACE.mkdir(parents=True, exist_ok=True)
if not (WORKSPACE / "state.json").exists():
    shutil.copytree(SEED_PATH, WORKSPACE, dirs_exist_ok=True)
    (WORKSPACE / "characters" / "player.md").write_text(
        "---\nid: char.player\nname: Rowan\nkind: character\n"
        "location: locations/lowmere/emberwick/village_square.md\n"
        "hp: {current: 24, max: 24}\nstats: {str: 16, dex: 14, con: 14, int: 12, wis: 12, cha: 14}\n"
        "stats_locked: true\n---\nA traveler passing through Emberwick.\n"
    )
    (WORKSPACE / "state.json").write_text(json.dumps({"state": "play", "active_agent": "dm", "player_character_id": "char.player"}))
write_project(WORKSPACE, WorldStore(WORKSPACE).ensure())
app = FastAPI()
module = MythfallModule()


@app.get('/module-release')
def module_release():
    root = Path(os.environ['MYTHFALL_UI_DIRECTORY'])
    files = []
    for path in ('panels.js', 'panels.css'):
        data = (root / path).read_bytes()
        files.append({'path': path, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    return {'id': 'mythfall-evaluation', 'manifest': {
        'files': files, 'client': {'contract': 1, 'panels': 'panels.js', 'styles': ['panels.css']},
    }}


@app.get('/module-files/{path}')
def module_file(path: str):
    if path not in ('panels.js', 'panels.css'):
        raise HTTPException(404)
    return FileResponse(Path(os.environ['MYTHFALL_UI_DIRECTORY']) / path)


def context(**extra):
    cls = ModuleActionContext if extra else ModuleSessionContext
    return cls(module_id="mythfall", session_uuid="8ddbb387-851d-44dc-acd1-9285b8c846d5", realm_id="Mythfall",
               archive_user_id=None, realm_session_id=None, workspace_root=WORKSPACE.parent,
               workspace_path=WORKSPACE, logger=logging.getLogger("mythfall-evaluation"), **extra)


if os.environ.get("MYTHFALL_RPG_EVALUATION") == "1":
    from mythfall.world_runtime import setup_world
    setup_world(context())


@app.post("/rpc")
def rpc(command: dict):
    kind, payload = command.get("type"), command.get("payload", {})
    try:
        if kind in {"workspace.read", "workspace.list"}:
            path = payload.get("path", "")
            candidate = (WORKSPACE / path).resolve()
            if not candidate.is_relative_to(WORKSPACE):
                raise ValueError("Path is outside the evaluation workspace.")
            if kind == "workspace.read":
                if not candidate.is_file():
                    raise ValueError(f"File not found: {path}")
                result = {"path": path, "content": candidate.read_text()}
            else:
                if not candidate.is_dir():
                    raise ValueError(f"Directory not found: {path}")
                result = {"path": path, "entries": [
                    {"name": entry.name, "path": entry.relative_to(WORKSPACE).as_posix(),
                     "kind": "directory" if entry.is_dir() else "file", "size": entry.stat().st_size}
                    for entry in sorted(candidate.iterdir())
                ]}
        elif kind == "realm.observe":
            result = module.on_observe(context())
        elif kind == "realm.action":
            result = module.on_action(context(operation_id=payload.get("operation_id"), payload=payload))
        else:
            raise ValueError("Unsupported evaluation command.")
        return {"type": kind + ".result", "payload": result}
    except ValueError as error:
        raise HTTPException(400, detail=str(error)) from error


@app.get("/workspace/{path:path}")
def workspace_file(path: str):
    candidate = (WORKSPACE / path).resolve()
    if not candidate.is_relative_to(WORKSPACE) or not candidate.is_file():
        raise HTTPException(404)
    return FileResponse(candidate)
