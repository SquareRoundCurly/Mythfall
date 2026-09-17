from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal


AgentMessageRole = Literal["user", "assistant", "system", "tool"]


@dataclass
class AgentMessage:
    role: AgentMessageRole
    content: str
    name: str | None = None


@dataclass
class ToolMessage:
    call_id: str
    name: str
    content: str


@dataclass
class ToolTrace:
    role: Literal["tool_call", "tool_result"]
    name: str
    content: str
    call_id: str


@dataclass
class VisibleEvent:
    speaker: str
    body: str
    event_type: str = "text"
    component: str | None = None
    payload: dict[str, Any] | None = None


@dataclass
class Context:
    messages: list[AgentMessage] = field(default_factory=list)
    pending_tool_results: list[ToolMessage] = field(default_factory=list)
    tool_traces: list[ToolTrace] = field(default_factory=list)
    visible_events: list[VisibleEvent] = field(default_factory=list)
    scratchpad: dict[str, Any] = field(default_factory=dict)
    workspace_path: Path | None = None
    event_sink: Callable[[str, dict[str, Any]], None] | None = None

    def add_message(
        self,
        role: AgentMessageRole,
        content: str,
        *,
        name: str | None = None,
    ) -> None:
        self.messages.append(AgentMessage(role=role, content=content, name=name))

    def publish_event(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.event_sink is None:
            return

        self.event_sink(event_type, payload)
