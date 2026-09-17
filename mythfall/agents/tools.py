from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from .context import Context


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    content: str
    data: dict[str, Any] = field(default_factory=dict)


class Tool(Protocol):
    spec: ToolSpec

    def run(self, context: Context, arguments: dict[str, Any]) -> ToolResult:
        ...


@dataclass(frozen=True)
class FunctionTool:
    spec: ToolSpec
    handler: Callable[[Context, dict[str, Any]], ToolResult]

    def run(self, context: Context, arguments: dict[str, Any]) -> ToolResult:
        return self.handler(context, arguments)
