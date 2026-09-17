from typing import Any

from .context import Context, VisibleEvent
from .tools import FunctionTool, ToolResult, ToolSpec


class EventToolError(ValueError):
    pass


def _publish_visible_event(context: Context, event: VisibleEvent) -> None:
    context.publish_event(
        "turn.visible_event",
        {
            "source": "agent_tool",
            "visible_event": {
                "speaker": event.speaker,
                "label": event.speaker,
                "role": "assistant",
                "event_type": event.event_type,
                "component": event.component,
                "payload": event.payload,
                "body": event.body,
            },
        },
    )


def emit_visible_event(context: Context, arguments: dict[str, Any]) -> ToolResult:
    speaker = str(arguments.get("speaker", "")).strip()
    body = str(arguments.get("body", "")).strip()

    if not speaker:
        raise EventToolError("speaker is required.")

    if not body:
        raise EventToolError("body is required.")

    event = VisibleEvent(speaker=speaker, body=body)
    context.visible_events.append(event)
    _publish_visible_event(context, event)

    return ToolResult(
        content=f"Emitted visible event from {speaker}.",
        data={
            "speaker": speaker,
        },
    )


def emit_visible_events(context: Context, arguments: dict[str, Any]) -> ToolResult:
    raw_events = arguments.get("events")
    if not isinstance(raw_events, list) or not raw_events:
        raise EventToolError("events must be a non-empty list.")

    emitted_events: list[VisibleEvent] = []
    for index, raw_event in enumerate(raw_events, start=1):
        if not isinstance(raw_event, dict):
            raise EventToolError(f"events[{index}] must be an object.")

        speaker = str(raw_event.get("speaker", "")).strip()
        body = str(raw_event.get("body", "")).strip()

        if not speaker:
            raise EventToolError(f"events[{index}].speaker is required.")

        if not body:
            raise EventToolError(f"events[{index}].body is required.")

        event = VisibleEvent(speaker=speaker, body=body)
        context.visible_events.append(event)
        emitted_events.append(event)
        _publish_visible_event(context, event)

    return ToolResult(
        content=f"Emitted {len(emitted_events)} visible events.",
        data={
            "events": [
                {
                    "speaker": event.speaker,
                }
                for event in emitted_events
            ],
        },
    )


def emit_component_event(context: Context, arguments: dict[str, Any]) -> ToolResult:
    speaker = str(arguments.get("speaker", "")).strip()
    component = str(arguments.get("component", "")).strip()
    body = str(arguments.get("body", "")).strip()
    props = arguments.get("props", {})

    if not speaker:
        raise EventToolError("speaker is required.")

    if not component:
        raise EventToolError("component is required.")

    if not isinstance(props, dict):
        raise EventToolError("props must be an object.")

    if not body:
        body = f"Interactive component: {component}"

    event = VisibleEvent(
        speaker=speaker,
        body=body,
        event_type="component",
        component=component,
        payload={
            "component": component,
            "props": props,
        },
    )
    context.visible_events.append(event)
    _publish_visible_event(context, event)

    return ToolResult(
        content=f"Emitted component event {component} from {speaker}.",
        data={
            "speaker": speaker,
            "component": component,
        },
    )


def event_tools() -> dict[str, FunctionTool]:
    return {
        "emit_visible_event": FunctionTool(
            spec=ToolSpec(
                name="emit_visible_event",
                description=(
                    "Emit a player-visible chat event for the current turn. "
                    "Use this for DM narration or NPC speech."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "speaker": {
                            "type": "string",
                            "description": "Visible speaker label, such as DM or an NPC name.",
                        },
                        "body": {
                            "type": "string",
                            "description": "Markdown body shown to the player.",
                        },
                    },
                    "required": ["speaker", "body"],
                },
            ),
            handler=emit_visible_event,
        ),
        "emit_visible_events": FunctionTool(
            spec=ToolSpec(
                name="emit_visible_events",
                description=(
                    "Emit ordered player-visible chat events for the current turn. "
                    "Use separate events for NPC dialogue and DM narration."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "events": {
                            "type": "array",
                            "minItems": 1,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "speaker": {
                                        "type": "string",
                                        "description": (
                                            "Visible speaker label, such as DM or an NPC name."
                                        ),
                                    },
                                    "body": {
                                        "type": "string",
                                        "description": "Markdown body shown to the player.",
                                    },
                                },
                                "required": ["speaker", "body"],
                            },
                        },
                    },
                    "required": ["events"],
                },
            ),
            handler=emit_visible_events,
        ),
        "emit_component_event": FunctionTool(
            spec=ToolSpec(
                name="emit_component_event",
                description=(
                    "Emit a player-visible interactive component message. "
                    "Use this for structured UI such as stat assignment."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "speaker": {"type": "string"},
                        "component": {
                            "type": "string",
                            "description": "Component name, such as stat_assignment.",
                        },
                        "body": {
                            "type": "string",
                            "description": "Fallback markdown text shown if the component is unavailable.",
                        },
                        "props": {
                            "type": "object",
                            "description": "Serializable props for the component.",
                        },
                    },
                    "required": ["speaker", "component", "props"],
                },
            ),
            handler=emit_component_event,
        ),
    }
