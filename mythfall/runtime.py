"""Mythfall session hooks."""

from datetime import datetime
from pathlib import Path
from typing import Iterable

from mythfall.llm import LLMReply, generate_reply
from mythfall.realm_state import (
    active_agent_config_path,
    ensure_realm_runtime_state,
    load_realm_runtime_state,
)
from mythfall.turns import begin_turn
from RealmEngine import networking
from RealmEngine.modules import ModuleComponentActionContext, ModuleMessageContext


def handle_message(context: ModuleMessageContext) -> None:
    turn = begin_turn(
        session_uuid=context.session_uuid,
        workspace_path=context.workspace_path,
        player_message=context.player_message,
        player_message_id=context.message_id,
    )
    _publish_turn_started(context, turn)
    runtime_state_before = ensure_realm_runtime_state(context.workspace_path)

    try:
        llm_reply, script_ran = _generate_creation_reply(
            context=context,
            recent_messages=context.messages,
            agent_config_path=active_agent_config_path(context.workspace_path),
            turn=turn,
        )
    except Exception:
        context.logger.exception("Mythfall could not generate a reply.")
        _publish_turn_failed(context, turn, "Mythfall could not generate a reply.")
        raise

    created_messages = _persist_reply_events(
        context=context,
        turn=turn,
        llm_reply=llm_reply,
        script_ran=script_ran,
    )

    runtime_state_after = load_realm_runtime_state(context.workspace_path)
    if _should_run_dm_opening(runtime_state_before, runtime_state_after):
        handoff_message = networking.send_message(
            context,
            body=_build_dm_opening_system_message(context.workspace_path),
            role="system",
            label="dm_opening_handoff",
        )
        _create_dm_opening_messages(
            context=context,
            recent_messages=[
                *context.messages,
                *created_messages,
                handoff_message,
            ],
        )

    _publish_turn_completed(context, turn)


def handle_component_action(context: ModuleComponentActionContext) -> None:
    from mythfall.component_actions import apply_component_action

    runtime_state_before = ensure_realm_runtime_state(context.workspace_path)
    next_message_payload = apply_component_action(context)
    networking.update_message_payload(
        context,
        message_id=context.message_id,
        payload=next_message_payload,
    )

    turn = begin_turn(
        session_uuid=context.session_uuid,
        workspace_path=context.workspace_path,
        player_message="Submitted stat assignment.",
        player_message_id=None,
    )
    _publish_turn_started(context, turn)

    try:
        hook_reply = generate_reply(
            context.messages,
            agent_config_path=active_agent_config_path(context.workspace_path),
            workspace_path=context.workspace_path,
            turn_file_path=turn.turn_file_path,
            hook="on_component_action",
            event_sink=_turn_realtime_event_sink(context, turn),
        )
    except Exception:
        context.logger.exception("Mythfall could not handle component action.")
        _publish_turn_failed(
            context,
            turn,
            "Mythfall could not handle component action.",
        )
        raise

    created_messages = _persist_component_events(
        context=context,
        turn=turn,
        hook_reply=hook_reply,
    )

    runtime_state_after = load_realm_runtime_state(context.workspace_path)
    if _should_run_dm_opening(runtime_state_before, runtime_state_after):
        handoff_message = networking.send_message(
            context,
            body=_build_dm_opening_system_message(context.workspace_path),
            role="system",
            label="dm_opening_handoff",
        )
        _create_dm_opening_messages(
            context=context,
            recent_messages=[
                *context.messages,
                *created_messages,
                handoff_message,
            ],
        )

    _publish_turn_completed(context, turn)


def _generate_creation_reply(
    *,
    context: ModuleMessageContext,
    recent_messages: Iterable,
    agent_config_path: Path,
    turn,
) -> tuple[LLMReply, bool]:
    # Character creation still uses its installed hook and data tools. Session
    # Python turn files are retained as legacy artifacts, never executed.
    reply = generate_reply(
        recent_messages,
        agent_config_path=agent_config_path,
        workspace_path=context.workspace_path,
        turn_file_path=turn.turn_file_path,
        event_sink=_turn_realtime_event_sink(context, turn),
    )
    return reply, False


def _persist_reply_events(
    *,
    context: ModuleMessageContext,
    turn,
    llm_reply: LLMReply,
    script_ran: bool,
) -> list:
    if script_ran:
        for event in turn.events:
            _publish_turn_event(context, turn, event)

    for tool_trace in llm_reply.tool_traces:
        turn.emit_debug(
            role=tool_trace.role,
            label=tool_trace.name,
            body=tool_trace.content,
        )

    if not script_ran:
        for visible_event in llm_reply.visible_events:
            turn.emit_visible(
                speaker=visible_event.speaker,
                body=visible_event.body,
                event_type=visible_event.event_type,
                component=visible_event.component,
                payload=visible_event.payload,
            )

    if not script_ran and not llm_reply.visible_events and llm_reply.text.strip():
        event = turn.emit_visible(speaker="DM", body=llm_reply.text)
        _publish_turn_event(context, turn, event)

    try:
        turn.require_generated_turn_file()
        turn.require_visible_events()
    except ValueError as error:
        _publish_turn_failed(context, turn, str(error))
        raise

    return _persist_turn_messages(context, turn, response_id=llm_reply.response_id)


def _persist_component_events(
    *,
    context: ModuleComponentActionContext,
    turn,
    hook_reply: LLMReply,
) -> list:
    for tool_trace in hook_reply.tool_traces:
        turn.emit_debug(
            role=tool_trace.role,
            label=tool_trace.name,
            body=tool_trace.content,
        )

    for visible_event in hook_reply.visible_events:
        turn.emit_visible(
            speaker=visible_event.speaker,
            body=visible_event.body,
            event_type=visible_event.event_type,
            component=visible_event.component,
            payload=visible_event.payload,
        )

    if not hook_reply.visible_events and hook_reply.text.strip():
        event = turn.emit_visible(
            speaker="Character Creator",
            body=hook_reply.text,
        )
        _publish_turn_event(context, turn, event)

    try:
        turn.require_visible_events()
    except ValueError as error:
        _publish_turn_failed(context, turn, str(error))
        raise

    return _persist_turn_messages(context, turn, response_id=None)


def _persist_turn_messages(context, turn, *, response_id: str | None) -> list:
    created_messages = []
    for event in turn.events:
        created_messages.append(
            networking.send_message(
                context,
                body=event.body,
                role=event.role or "assistant",
                label=event.label,
                event_type=event.event_type,
                component=event.component,
                payload=event.payload,
                openai_response_id=(
                    response_id
                    if event.kind == "visible" and event is turn.events[-1]
                    else None
                ),
            ),
        )

    return created_messages


def _create_dm_opening_messages(
    *,
    context,
    recent_messages: list,
) -> None:
    from mythfall.world_runtime import open_adventure
    open_adventure(context)


def _publish_turn_started(context, turn) -> None:
    networking.publish_event(
        context,
        "turn.started",
        {
            "turn_number": turn.number,
            "player_message_id": turn.player_message_id,
            "started_at": turn.started_at.isoformat(),
        },
    )


def _publish_turn_event(context, turn, event) -> None:
    if event.kind == "visible":
        event_type = "turn.visible_event"
    elif event.role == "tool_call":
        event_type = "agent.tool_call"
    elif event.role == "tool_result":
        event_type = "agent.tool_result"
    else:
        event_type = "turn.debug_event"

    networking.publish_event(
        context,
        event_type,
        {
            "turn_number": turn.number,
            "event": event.to_record(),
        },
    )


def _publish_turn_completed(context, turn) -> None:
    networking.publish_event(
        context,
        "turn.completed",
        {
            "turn_number": turn.number,
            "completed_at": datetime.utcnow().isoformat(),
        },
    )


def _publish_turn_failed(context, turn, error: str) -> None:
    networking.publish_event(
        context,
        "turn.failed",
        {
            "turn_number": turn.number,
            "error": error,
            "failed_at": datetime.utcnow().isoformat(),
        },
    )


def _turn_realtime_event_sink(context, turn):
    def event_sink(event_type: str, payload: dict) -> None:
        networking.publish_event(
            context,
            event_type,
            {
                "turn_number": turn.number,
                **payload,
            },
        )

    return event_sink


def _build_dm_opening_system_message(workspace_path) -> str:
    player_character_path = workspace_path / "characters" / "player.md"
    player_character = (
        player_character_path.read_text(encoding="utf-8")
        if player_character_path.exists()
        else "(player character file missing)"
    )

    return (
        "Character creation is complete and the realm has transitioned to play.\n\n"
        "This is a hidden system handoff for the Dungeon Master. On your next "
        "response, open the adventure immediately. Introduce where the player "
        "character is, the mood of the local setting, and one or two immediate "
        "points of interest or hooks. Do not ask if the player is ready. Do not "
        "repeat the character creation checklist. Use visible DM narration and "
        "NPC speech events as appropriate.\n\n"
        "Current player character file `characters/player.md`:\n\n"
        f"{player_character}"
    )


def _should_run_dm_opening(runtime_state_before, runtime_state_after) -> bool:
    return (
        runtime_state_before.active_agent == "character_creator"
        and runtime_state_after.state == "play"
        and runtime_state_after.active_agent == "dm"
    )
