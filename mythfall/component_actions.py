from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from mythfall.realm_state import update_character_creation_checklist
from mythfall.realms import RealmValidationError, load_realm, validate_realm_write
from RealmEngine import workspaces
from RealmEngine.modules import ModuleComponentActionContext


class ComponentActionError(ValueError):
    pass


def apply_component_action(
    context: ModuleComponentActionContext,
) -> dict[str, Any]:
    if (
        context.component != "stat_assignment"
        or context.action != "submit_stat_assignment"
    ):
        raise ComponentActionError("Unsupported component action.")

    stats = _validate_stat_assignment_payload(context.payload)
    validation_error = _apply_player_stats(context.workspace_path, stats)
    update_character_creation_checklist(
        context.workspace_path,
        stats_assigned=True,
        sheet_valid=validation_error is None,
    )

    return {
        **context.message_payload,
        "submitted": True,
        "submitted_payload": context.payload,
        "validation_error": validation_error,
    }


def _validate_stat_assignment_payload(payload: dict[str, Any]) -> dict[str, int]:
    stats = payload.get("stats")
    values = payload.get("values")
    assignments = payload.get("assignments")

    if (
        not isinstance(stats, list)
        or not isinstance(values, list)
        or not isinstance(assignments, dict)
    ):
        raise ComponentActionError(
            "Stat assignment payload must include stats, values, and assignments.",
        )

    expected_stats = {
        "strength": "str",
        "dexterity": "dex",
        "constitution": "con",
        "intelligence": "int",
        "wisdom": "wis",
        "charisma": "cha",
    }
    if set(stats) != set(expected_stats):
        raise ComponentActionError("Stat assignment must include the six base stats.")

    if set(assignments) != set(expected_stats):
        raise ComponentActionError("Every base stat must be assigned.")

    values_by_id: dict[str, int] = {}
    for index, raw_value in enumerate(values):
        if not isinstance(raw_value, dict):
            raise ComponentActionError(f"Stat roll value {index} must be an object.")

        value_id = str(raw_value.get("id", "")).strip()
        value = raw_value.get("value")

        if not value_id:
            raise ComponentActionError(f"Stat roll value {index} is missing an id.")

        if value_id in values_by_id:
            raise ComponentActionError(f"Duplicate stat roll id: {value_id}")

        if not isinstance(value, int) or isinstance(value, bool):
            raise ComponentActionError(f"Invalid stat roll value for {value_id}.")

        if value < 3 or value > 18:
            raise ComponentActionError(f"Stat roll value out of range for {value_id}.")

        values_by_id[value_id] = value

    if len(values_by_id) != 6:
        raise ComponentActionError("Exactly six rolled values are required.")

    parsed_assignments: dict[str, int] = {}
    used_value_ids: list[str] = []
    for stat in stats:
        value_id = assignments.get(stat)
        if not isinstance(value_id, str):
            raise ComponentActionError(f"Invalid assigned roll id for {stat}.")

        if value_id not in values_by_id:
            raise ComponentActionError(f"Unknown assigned roll id for {stat}.")

        used_value_ids.append(value_id)
        parsed_assignments[expected_stats[stat]] = values_by_id[value_id]

    if len(set(used_value_ids)) != len(used_value_ids):
        raise ComponentActionError("Assigned roll ids must be used once each.")

    return parsed_assignments


def _apply_player_stats(workspace_path: Path, stats: dict[str, int]) -> str | None:
    relative_path = "characters/player.md"
    player_path = workspace_path / relative_path
    if not player_path.exists():
        raise ComponentActionError("Player character draft does not exist.")

    content = player_path.read_text(encoding="utf-8")
    if not content.startswith("---\n"):
        raise ComponentActionError("Player character draft is missing frontmatter.")

    try:
        _, frontmatter_text, body = content.split("---", 2)
        frontmatter = yaml.safe_load(frontmatter_text) or {}
    except Exception as error:
        raise ComponentActionError(
            "Player character draft frontmatter is invalid.",
        ) from error

    if not isinstance(frontmatter, dict):
        raise ComponentActionError(
            "Player character draft frontmatter must be a mapping.",
        )

    frontmatter["stats"] = stats
    frontmatter["stats_locked"] = True
    frontmatter["stats_source"] = "stat_assignment"
    next_content = (
        "---\n"
        f"{yaml.safe_dump(frontmatter, sort_keys=False)}"
        "---"
        f"{body}"
    )

    validation_error: str | None = None
    try:
        validate_realm_write(
            load_realm(workspace_path),
            player_path.relative_to(workspace_path),
            content=next_content,
            exists=True,
        )
    except RealmValidationError as error:
        validation_error = str(error)

    workspaces.write_text(workspace_path, relative_path, next_content)
    return validation_error
