from pathlib import Path

import yaml

from mythfall.agents import AgentResult
from mythfall.realm_state import (
    ensure_realm_runtime_state,
    set_realm_runtime_state,
    update_character_creation_checklist,
)


SPEAKER = "Character Creator"
PHASE_COLLECT_CONCEPT = "collect_concept"
PHASE_ASSIGN_STATS = "assign_stats"
PHASE_REVIEW_SHEET = "review_sheet"
PHASE_CONFIRM_BEGIN = "confirm_begin"
PHASE_COMPLETE = "complete"
STAT_PROPS = {
    "method": "4d6_drop_lowest",
    "stats": [
        "strength",
        "dexterity",
        "constitution",
        "intelligence",
        "wisdom",
        "charisma",
    ],
}


def on_created(context):
    context.emit_text(
        speaker=SPEAKER,
        body=(
            "Welcome to Mythfall. Before the realm begins, describe the character "
            "you want to play. A name, a vibe, what they are good at, and what "
            "kind of trouble they are walking toward is enough."
        ),
    )
    return AgentResult(text="")


def on_message(context):
    workspace_path = _workspace_path(context)
    state = ensure_realm_runtime_state(workspace_path)
    checklist = state.character_creation

    if (
        checklist
        and checklist.stats_assigned
        and checklist.concept_confirmed
        and checklist.sheet_valid
        and _is_ready_message(context.latest_user_message())
    ):
        return _transition_to_play(context)

    result = context.run_llm()
    state = ensure_realm_runtime_state(workspace_path)
    checklist = state.character_creation
    latest_message_is_ready = _is_ready_message(context.latest_user_message())
    if checklist and not checklist.stats_assigned and latest_message_is_ready:
        update_character_creation_checklist(
            workspace_path,
            phase=PHASE_ASSIGN_STATS,
            concept_confirmed=True,
            player_confirmed=True,
        )
        state = ensure_realm_runtime_state(workspace_path)
        checklist = state.character_creation

    if (
        checklist
        and not checklist.stats_assigned
        and (_prompted_ready_too_early(context) or latest_message_is_ready)
        and not _has_stat_assignment_component(context)
    ):
        update_character_creation_checklist(
            workspace_path,
            phase=PHASE_ASSIGN_STATS,
            concept_confirmed=True,
        )
        context.clear_visible_events()
        _emit_stats_assignment(context)
        state = ensure_realm_runtime_state(workspace_path)
        checklist = state.character_creation

    if (
        checklist
        and checklist.concept_confirmed
        and not checklist.stats_assigned
        and not _has_stat_assignment_component(context)
    ):
        update_character_creation_checklist(
            workspace_path,
            phase=PHASE_ASSIGN_STATS,
        )
        _emit_stats_assignment(context)

    return result


def on_component_action(context):
    workspace_path = _workspace_path(context)
    state = ensure_realm_runtime_state(workspace_path)
    checklist = state.character_creation
    if checklist is None or not checklist.stats_assigned:
        return AgentResult(text="")

    player = _load_player(workspace_path)
    if player is None:
        update_character_creation_checklist(
            workspace_path,
            phase=PHASE_REVIEW_SHEET,
        )
        context.emit_text(
            speaker=SPEAKER,
            body="Stats are assigned, but I still need a character draft before we begin.",
        )
        return AgentResult(text="")

    update_character_creation_checklist(
        workspace_path,
        phase=PHASE_CONFIRM_BEGIN,
        concept_confirmed=True,
        sheet_valid=True,
    )
    state = ensure_realm_runtime_state(workspace_path)
    checklist = state.character_creation
    if checklist and checklist.player_confirmed:
        return _transition_to_play(context)

    context.emit_text(
        speaker=SPEAKER,
        body=(
            f"Stats assigned for {player['name']}: {_format_stats(player['stats'])}.\n\n"
            "If this character is ready, say **begin** and I will open the realm."
        ),
    )
    return AgentResult(text="")


def _transition_to_play(context):
    workspace_path = _workspace_path(context)
    player = _load_player(workspace_path)
    player_name = player["name"] if player else "your character"
    update_character_creation_checklist(
        workspace_path,
        phase=PHASE_COMPLETE,
        concept_confirmed=True,
        sheet_valid=True,
        player_confirmed=True,
    )
    context.write_turn_file(
        "---\n"
        "player_intent: Begin play after character creation.\n"
        "---\n\n"
        f"Character creation completed for {player_name}. The realm state moved to play.\n",
    )
    set_realm_runtime_state(
        workspace_path,
        next_state="play",
        player_character_id="char.player",
    )
    context.emit_text(
        speaker=SPEAKER,
        body=f"{player_name} is ready. The realm is opening now.",
    )
    return AgentResult(text="")


def _emit_stats_assignment(context):
    context.emit_component(
        speaker=SPEAKER,
        component="stat_assignment",
        body="Assign your rolled stats.",
        props=STAT_PROPS,
    )


def _prompted_ready_too_early(context) -> bool:
    text = "\n".join(
        event.body.lower()
        for event in context.agent.context.visible_events
        if event.speaker == SPEAKER
    )
    return any(phrase in text for phrase in ("say **ready**", "say ready", "ready to begin"))


def _has_stat_assignment_component(context) -> bool:
    return any(
        event.component == "stat_assignment"
        for event in context.agent.context.visible_events
    )


def _is_ready_message(message):
    normalized = message.lower()
    return any(word in normalized for word in ("ready", "begin", "start", "let's go"))


def _workspace_path(context):
    if context.workspace_path is None:
        raise ValueError("Character creator requires a workspace path.")

    return context.workspace_path


def _load_player(workspace_path: Path):
    player_path = workspace_path / "characters" / "player.md"
    if not player_path.exists():
        return None

    content = player_path.read_text(encoding="utf-8")
    if not content.startswith("---\n"):
        return None

    try:
        _, frontmatter_text, _ = content.split("---", 2)
    except ValueError:
        return None

    frontmatter = yaml.safe_load(frontmatter_text) or {}
    if not isinstance(frontmatter, dict):
        return None

    stats = frontmatter.get("stats")
    if not isinstance(stats, dict):
        return None

    required_stats = ("str", "dex", "con", "int", "wis", "cha")
    if any(stat not in stats for stat in required_stats):
        return None

    return {
        "name": str(frontmatter.get("name") or "your character"),
        "stats": stats,
    }


def _format_stats(stats):
    labels = [
        ("STR", "str"),
        ("DEX", "dex"),
        ("CON", "con"),
        ("INT", "int"),
        ("WIS", "wis"),
        ("CHA", "cha"),
    ]
    return ", ".join(f"{label} {stats[key]}" for label, key in labels)
