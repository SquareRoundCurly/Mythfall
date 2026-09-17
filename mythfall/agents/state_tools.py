from typing import Any

import yaml

from .context import Context
from .tools import FunctionTool, ToolResult, ToolSpec
from mythfall.realm_state import (
    ensure_realm_runtime_state,
    set_realm_runtime_state,
    update_character_creation_checklist,
)
from mythfall.realms import RealmValidationError, load_realm, validate_realm_write


class StateToolError(ValueError):
    pass


def set_realm_state(context: Context, arguments: dict[str, Any]) -> ToolResult:
    if context.workspace_path is None:
        raise StateToolError("Context does not have a workspace path.")

    next_state = str(arguments.get("state", "")).strip()
    if not next_state:
        raise StateToolError("state is required.")

    player_character_id = arguments.get("player_character_id")
    if player_character_id is not None:
        player_character_id = str(player_character_id).strip() or None

    player_character_path = arguments.get("player_character_path")
    if player_character_path is not None:
        player_character_path = str(player_character_path).strip() or None

    if next_state == "play":
        _validate_player_character_file(
            context,
            player_character_path or "characters/player.md",
            require_stats=True,
        )
        _validate_character_creation_checklist(context)

    state = set_realm_runtime_state(
        context.workspace_path,
        next_state=next_state,
        player_character_id=player_character_id,
    )

    return ToolResult(
        content=(
            f"Realm state set to {state.state}. "
            f"Active agent is {state.active_agent or 'none'}."
        ),
        data=state.to_record(),
    )


def mark_character_creation_checklist(
    context: Context,
    arguments: dict[str, Any],
) -> ToolResult:
    if context.workspace_path is None:
        raise StateToolError("Context does not have a workspace path.")

    allowed_keys = {
        "phase",
        "concept_confirmed",
        "sheet_valid",
        "player_confirmed",
    }
    updates = {}
    for key in allowed_keys:
        if key not in arguments:
            continue

        updates[key] = str(arguments[key]) if key == "phase" else bool(arguments[key])

    if not updates:
        raise StateToolError("At least one checklist field is required.")

    if "stats_assigned" in arguments:
        raise StateToolError(
            "stats_assigned is set only by the stat assignment component submit action.",
        )

    state = update_character_creation_checklist(context.workspace_path, **updates)
    checklist = state.character_creation

    return ToolResult(
        content=(
            "Updated character creation checklist: "
            f"{checklist.to_record() if checklist else {}}"
        ),
        data=checklist.to_record() if checklist else {},
    )


def state_tools() -> dict[str, FunctionTool]:
    return {
        "mark_character_creation_checklist": FunctionTool(
            spec=ToolSpec(
                name="mark_character_creation_checklist",
                description=(
                    "Update programmatic character creation checklist flags. "
                    "Use this during character creation after player confirmation "
                    "or after verifying the sheet. This cannot set stats_assigned."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "concept_confirmed": {"type": "boolean"},
                        "phase": {
                            "type": "string",
                            "enum": [
                                "collect_concept",
                                "assign_stats",
                                "review_sheet",
                                "confirm_begin",
                                "complete",
                            ],
                        },
                        "sheet_valid": {"type": "boolean"},
                        "player_confirmed": {"type": "boolean"},
                    },
                },
            ),
            handler=mark_character_creation_checklist,
        ),
        "set_realm_state": FunctionTool(
            spec=ToolSpec(
                name="set_realm_state",
                description=(
                    "Transition the current realm to another declared state. "
                    "Use this after character creation is ready to enter play."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "state": {
                            "type": "string",
                            "description": "Target realm state, such as play.",
                        },
                        "player_character_path": {
                            "type": "string",
                            "description": (
                                "Path to the player character markdown file. "
                                "Defaults to characters/player.md."
                            ),
                        },
                        "player_character_id": {
                            "type": "string",
                            "description": (
                                "Optional player character id to store in realm state."
                            ),
                        },
                    },
                    "required": ["state"],
                },
            ),
            handler=set_realm_state,
        ),
    }


def _validate_player_character_file(
    context: Context,
    relative_path_text: str,
    *,
    require_stats: bool = False,
) -> None:
    if context.workspace_path is None:
        raise StateToolError("Context does not have a workspace path.")

    relative_path = _validate_relative_path(relative_path_text)
    path = context.workspace_path / relative_path
    if not path.exists() or not path.is_file():
        raise StateToolError(f"Player character file does not exist: {relative_path_text}")

    try:
        content = path.read_text(encoding="utf-8")
        validate_realm_write(
            load_realm(context.workspace_path),
            relative_path,
            content=content,
            exists=True,
        )
        if require_stats:
            _validate_player_character_stats(content)
    except RealmValidationError as error:
        raise StateToolError(f"Player character file is invalid: {error}") from error


def _validate_character_creation_checklist(context: Context) -> None:
    if context.workspace_path is None:
        raise StateToolError("Context does not have a workspace path.")

    runtime_state = ensure_realm_runtime_state(context.workspace_path)
    checklist = runtime_state.character_creation
    if checklist is None:
        return

    missing = [
        key
        for key, value in checklist.to_record().items()
        if not value
    ]
    if missing:
        raise StateToolError(
            "Character creation is not ready for play. Missing checklist flags: "
            f"{', '.join(missing)}",
        )


def _validate_player_character_stats(content: str) -> None:
    frontmatter = _parse_frontmatter(content)
    stats = frontmatter.get("stats")
    if not isinstance(stats, dict):
        raise StateToolError("Player character stats are required before play.")

    missing_stats = [
        stat
        for stat in ("str", "dex", "con", "int", "wis", "cha")
        if stat not in stats
    ]
    if missing_stats:
        raise StateToolError(
            "Player character stats are incomplete: "
            f"{', '.join(missing_stats)}",
        )

    if frontmatter.get("stats_locked") is not True:
        raise StateToolError(
            "Player character stats must be assigned through the stat widget before play.",
        )


def _parse_frontmatter(content: str) -> dict[str, Any]:
    if not content.startswith("---\n"):
        return {}

    try:
        _, frontmatter_text, _ = content.split("---", 2)
    except ValueError:
        return {}

    parsed = yaml.safe_load(frontmatter_text) or {}
    return parsed if isinstance(parsed, dict) else {}


def _validate_relative_path(path_text: str):
    from pathlib import Path

    relative_path = Path(path_text)
    if relative_path.is_absolute():
        raise StateToolError("Player character path must be relative.")

    if ".." in relative_path.parts:
        raise StateToolError("Player character path must not contain parent segments.")

    if relative_path.as_posix() != "characters/player.md":
        raise StateToolError("Player character must be stored at characters/player.md.")

    return relative_path
