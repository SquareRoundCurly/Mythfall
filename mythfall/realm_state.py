from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from RealmEngine.modules import RealmStateDefinition, get_module


REALM_STATE_FILE = "state.json"


@dataclass(frozen=True)
class CharacterCreationChecklist:
    phase: str = "collect_concept"
    concept_confirmed: bool = False
    stats_assigned: bool = False
    sheet_valid: bool = False
    player_confirmed: bool = False

    def to_record(self) -> dict[str, str | bool]:
        return {
            "phase": self.phase,
            "concept_confirmed": self.concept_confirmed,
            "stats_assigned": self.stats_assigned,
            "sheet_valid": self.sheet_valid,
            "player_confirmed": self.player_confirmed,
        }


@dataclass(frozen=True)
class RealmRuntimeState:
    state: str
    active_agent: str | None = None
    player_character_id: str | None = None
    character_creation: CharacterCreationChecklist | None = None

    def to_record(self) -> dict[str, str | dict[str, bool] | None]:
        record: dict[str, str | dict[str, bool] | None] = {
            "state": self.state,
            "active_agent": self.active_agent,
            "player_character_id": self.player_character_id,
        }

        if self.character_creation is not None:
            record["character_creation"] = self.character_creation.to_record()

        return record


def ensure_realm_runtime_state(workspace_path: Path) -> RealmRuntimeState:
    state_path = workspace_path / REALM_STATE_FILE
    if state_path.exists():
        return load_realm_runtime_state(workspace_path)

    realm_module = get_module("mythfall")
    state_id = realm_module.initial_state
    state_definition = _state_definition(realm_module, state_id)
    state = RealmRuntimeState(
        state=state_id,
        active_agent=state_definition.agent if state_definition else None,
        player_character_id=None,
        character_creation=(
            CharacterCreationChecklist()
            if state_definition and state_definition.agent == "character_creator"
            else None
        ),
    )
    _write_state(state_path, state)
    return state


def load_realm_runtime_state(workspace_path: Path) -> RealmRuntimeState:
    state_path = workspace_path / REALM_STATE_FILE
    with state_path.open(encoding="utf-8") as state_file:
        state_data: dict[str, Any] = json.load(state_file)

    return RealmRuntimeState(
        state=str(state_data["state"]),
        active_agent=(
            str(state_data["active_agent"])
            if state_data.get("active_agent") is not None
            else None
        ),
        player_character_id=(
            str(state_data["player_character_id"])
            if state_data.get("player_character_id") is not None
            else None
        ),
        character_creation=_parse_character_creation_checklist(
            state_data.get("character_creation"),
        ),
    )


def set_realm_runtime_state(
    workspace_path: Path,
    *,
    next_state: str,
    player_character_id: str | None = None,
) -> RealmRuntimeState:
    realm_module = get_module("mythfall")
    current_state = ensure_realm_runtime_state(workspace_path)
    current_definition = _state_definition(realm_module, current_state.state)
    next_definition = _state_definition(realm_module, next_state)

    if next_definition is None:
        raise ValueError(f"Unknown realm state: {next_state}")

    allowed_next_states = current_definition.next if current_definition else []
    if next_state != current_state.state and next_state not in allowed_next_states:
        raise ValueError(
            f"Cannot transition realm state from {current_state.state} to {next_state}.",
        )

    state = RealmRuntimeState(
        state=next_state,
        active_agent=next_definition.agent,
        player_character_id=(
            player_character_id
            if player_character_id is not None
            else current_state.player_character_id
        ),
        character_creation=(
            current_state.character_creation
            if next_definition.agent == "character_creator"
            else current_state.character_creation
        ),
    )
    _write_state(workspace_path / REALM_STATE_FILE, state)
    return state


def update_character_creation_checklist(
    workspace_path: Path,
    **updates: str | bool,
) -> RealmRuntimeState:
    current_state = ensure_realm_runtime_state(workspace_path)
    current_checklist = (
        current_state.character_creation
        or CharacterCreationChecklist()
    )
    values = current_checklist.to_record()

    for key, value in updates.items():
        if key not in values:
            raise ValueError(f"Unknown character creation checklist item: {key}")
        if key == "phase":
            values[key] = str(value)
        else:
            values[key] = bool(value)

    next_state = RealmRuntimeState(
        state=current_state.state,
        active_agent=current_state.active_agent,
        player_character_id=current_state.player_character_id,
        character_creation=CharacterCreationChecklist(**values),
    )
    _write_state(workspace_path / REALM_STATE_FILE, next_state)
    return next_state


def active_state_definition(workspace_path: Path) -> RealmStateDefinition | None:
    realm_module = get_module("mythfall")
    runtime_state = ensure_realm_runtime_state(workspace_path)
    return _state_definition(realm_module, runtime_state.state)


def active_agent_config_path(workspace_path: Path) -> Path:
    runtime_state = ensure_realm_runtime_state(workspace_path)
    if runtime_state.active_agent is None:
        raise ValueError(f"Realm state has no active agent: {runtime_state.state}")

    agent_config_path = workspace_path / "agents" / runtime_state.active_agent
    if agent_config_path.is_dir():
        return agent_config_path

    if not agent_config_path.exists():
        legacy_config_path = agent_config_path.with_suffix(".json")
        if legacy_config_path.exists():
            return legacy_config_path

        raise ValueError(f"Active agent config does not exist: {agent_config_path}")

    return agent_config_path


def _state_definition(
    realm: Any,
    state: str,
) -> RealmStateDefinition | None:
    return realm.state_definitions().get(state)


def _parse_character_creation_checklist(
    value: Any,
) -> CharacterCreationChecklist | None:
    if not isinstance(value, dict):
        return None

    return CharacterCreationChecklist(
        phase=str(value.get("phase", "collect_concept")),
        concept_confirmed=bool(value.get("concept_confirmed", False)),
        stats_assigned=bool(value.get("stats_assigned", False)),
        sheet_valid=bool(value.get("sheet_valid", False)),
        player_confirmed=bool(value.get("player_confirmed", False)),
    )


def _write_state(state_path: Path, state: RealmRuntimeState) -> None:
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=state_path.parent,
        delete=False,
    ) as temp_file:
        json.dump(state.to_record(), temp_file, indent=2, sort_keys=True)
        temp_file.write("\n")
        temp_path = Path(temp_file.name)

    temp_path.replace(state_path)
