from dataclasses import dataclass, field
from typing import Any, Protocol

from .tools import Tool

@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    id: str | None = None


@dataclass(frozen=True)
class AgentResult:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    provider_response_id: str | None = None


class ModelProvider(Protocol):
    def run(self, agent: Any, tools: list[Tool]) -> AgentResult:
        ...
