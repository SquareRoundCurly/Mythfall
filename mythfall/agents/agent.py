import json
import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from .config import AgentConfig
from .context import Context, ToolMessage, ToolTrace, VisibleEvent
from .event_tools import event_tools
from .file_tools import filesystem_tools
from .providers import AgentResult, ModelProvider, ToolCall
from .state_tools import state_tools
from .tools import Tool
from mythfall.turns import TURN_FILE_PLACEHOLDER


TURN_FILE_REQUIRED_MESSAGE = (
    "You tried to finish the turn before writing the required current turn.md. "
    "Write the current turn file now with `write_file`. It must be markdown "
    "with YAML frontmatter containing `player_intent`, followed by short turn "
    "notes. If visible events were already emitted, do not repeat them unless "
    "you need to correct them."
)


@dataclass
class Agent:
    config: AgentConfig
    instructions: str
    config_path: Path
    context: Context = field(default_factory=Context)

    def run(self, provider: ModelProvider, *, hook: str = "on_message") -> AgentResult:
        script_hook = self._load_script_hook(hook)
        if script_hook is not None:
            hook_context = AgentHookContext(agent=self, provider=provider)
            result = script_hook(hook_context)
            if isinstance(result, AgentResult):
                return result
            return AgentResult(text="")

        if hook != "on_message":
            return AgentResult(text="")

        return self.run_llm(provider)

    def run_llm(self, provider: ModelProvider) -> AgentResult:
        self.context.scratchpad["agent_id"] = self.config.id
        tools = self._allowed_tools()

        for _ in range(self.config.max_iterations):
            result = provider.run(self, list(tools.values()))

            if not result.tool_calls:
                if self._requires_turn_file_before_finish():
                    self.context.pending_tool_results = []
                    self.context.add_message("system", TURN_FILE_REQUIRED_MESSAGE)
                    continue

                self.context.pending_tool_results = []
                return result

            self.context.pending_tool_results = [
                self._run_tool_call(tools, tool_call)
                for tool_call in result.tool_calls
            ]

        raise RuntimeError(
            f"Agent {self.config.id} exceeded {self.config.max_iterations} iterations.",
        )

    def _load_script_hook(
        self,
        hook: str,
    ) -> Callable[["AgentHookContext"], AgentResult | None] | None:
        script_path = self._script_path()
        if script_path is None:
            return None

        module = _load_script_module(script_path)
        script_hook = getattr(module, hook, None)
        if script_hook is None:
            return None

        if not callable(script_hook):
            raise TypeError(f"Agent hook is not callable: {script_path}:{hook}")

        return script_hook

    def _allowed_tools(self) -> dict[str, Tool]:
        available_tools = {
            **filesystem_tools(),
            **event_tools(),
            **state_tools(),
        }
        return {
            name: tool
            for name, tool in available_tools.items()
            if name in self.config.tools
        }

    def _run_tool_call(self, tools: dict[str, Tool], tool_call) -> ToolMessage:
        call_id = tool_call.id or tool_call.name
        arguments_json = json.dumps(tool_call.arguments, indent=2, sort_keys=True)
        self.context.tool_traces.append(
            ToolTrace(
                role="tool_call",
                name=tool_call.name,
                call_id=call_id,
                content=arguments_json,
            ),
        )
        self.context.publish_event(
            "agent.tool_call",
            {
                "agent_id": self.config.id,
                "tool_call": {
                    "call_id": call_id,
                    "name": tool_call.name,
                    "arguments": tool_call.arguments,
                    "content": arguments_json,
                },
            },
        )
        tool = tools.get(tool_call.name)

        if tool is None:
            tool_message = ToolMessage(
                call_id=call_id,
                name=tool_call.name,
                content=f"Tool is not available: {tool_call.name}",
            )
            self._trace_tool_result(tool_message)
            return tool_message

        try:
            result = tool.run(self.context, tool_call.arguments)
            content = result.content
        except Exception as error:
            content = f"Tool {tool_call.name} failed: {error}"

        tool_message = ToolMessage(
            call_id=call_id,
            name=tool_call.name,
            content=content,
        )
        self._trace_tool_result(tool_message)
        return tool_message

    def _trace_tool_result(self, tool_message: ToolMessage) -> None:
        self.context.tool_traces.append(
            ToolTrace(
                role="tool_result",
                name=tool_message.name,
                call_id=tool_message.call_id,
                content=tool_message.content,
            ),
        )
        self.context.publish_event(
            "agent.tool_result",
            {
                "agent_id": self.config.id,
                "tool_result": {
                    "call_id": tool_message.call_id,
                    "name": tool_message.name,
                    "content": tool_message.content,
                },
            },
        )

    def _script_path(self) -> Path | None:
        if self.config.script is None:
            return None

        # Hooks execute with server authority. Session-authored files may supply
        # setting data, but cannot replace installed Python rules.
        if self.config.id not in {"character_creator", "dm"}:
            raise ValueError("Unknown installed Mythfall agent hook.")
        script_path = Path(__file__).resolve().parents[1] / "seed" / "agents" / self.config.id / "agent.py"
        if not script_path.exists():
            raise FileNotFoundError(f"Agent script does not exist: {script_path}")

        return script_path

    def _requires_turn_file_before_finish(self) -> bool:
        turn_file_path = self.context.scratchpad.get("turn_file_path")
        if self.context.workspace_path is None or not turn_file_path:
            return False

        path = self.context.workspace_path / str(turn_file_path)
        if not path.exists():
            return True

        content = path.read_text(encoding="utf-8")
        return not content.strip() or content == TURN_FILE_PLACEHOLDER


class AgentHookContext:
    def __init__(self, *, agent: Agent, provider: ModelProvider) -> None:
        self.agent = agent
        self.provider = provider

    @property
    def workspace_path(self) -> Path | None:
        return self.agent.context.workspace_path

    @property
    def scratchpad(self) -> dict[str, Any]:
        return self.agent.context.scratchpad

    @property
    def messages(self):
        return self.agent.context.messages

    def latest_user_message(self) -> str:
        for message in reversed(self.agent.context.messages):
            if message.role == "user":
                return message.content
        return ""

    def run_llm(self) -> AgentResult:
        return self.agent.run_llm(self.provider)

    def clear_visible_events(self) -> None:
        self.agent.context.visible_events.clear()

    def emit_text(self, *, speaker: str, body: str) -> None:
        self.agent.context.visible_events.append(
            VisibleEvent(speaker=speaker, body=body),
        )

    def emit_component(
        self,
        *,
        speaker: str,
        component: str,
        body: str,
        props: dict[str, Any],
    ) -> None:
        self.agent.context.visible_events.append(
            VisibleEvent(
                speaker=speaker,
                body=body,
                event_type="component",
                component=component,
                payload={
                    "component": component,
                    "props": props,
                },
            ),
        )

    def run_tool(self, name: str, arguments: dict[str, Any]) -> ToolMessage:
        return self.agent._run_tool_call(
            self.agent._allowed_tools(),
            ToolCall(name=name, arguments=arguments),
        )

    def write_turn_file(self, content: str) -> ToolMessage:
        turn_file_path = self.scratchpad.get("turn_file_path")
        if not turn_file_path:
            raise ValueError("No current turn file is available.")

        return self.run_tool(
            "write_file",
            {
                "path": str(turn_file_path),
                "content": content,
                "overwrite": True,
            },
        )


def load_agent(config_path: Path, *, context: Context | None = None) -> Agent:
    config_path = _resolve_agent_config_path(config_path)
    config = AgentConfig.from_json_file(config_path)
    instructions_path = config_path.parent / config.instructions
    instructions = instructions_path.read_text(encoding="utf-8").strip()

    return Agent(
        config=config,
        instructions=instructions,
        config_path=config_path,
        context=context or Context(),
    )


def _resolve_agent_config_path(config_path: Path) -> Path:
    if config_path.is_dir():
        config_path = config_path / "agent.json"

    if config_path.exists():
        return config_path

    if config_path.name.endswith(".json"):
        folder_config_path = config_path.with_suffix("") / "agent.json"
        if folder_config_path.exists():
            return folder_config_path

    raise FileNotFoundError(f"Agent config does not exist: {config_path}")


def _load_script_module(script_path: Path) -> ModuleType:
    module_name = (
        "realm_agent_"
        f"{script_path.parent.name}_"
        f"{abs(hash(script_path.resolve()))}"
    )
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load agent script: {script_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
