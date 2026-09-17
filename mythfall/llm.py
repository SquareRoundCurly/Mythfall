from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from archive_db.models import Message
from dotenv import load_dotenv
from openai import OpenAI

from .agents import AgentMessage, Context, ToolTrace, VisibleEvent, load_agent
from .agents.openai_provider import OpenAIModelProvider

load_dotenv(Path(__file__).resolve().parents[3] / "RealmEngine" / ".env", override=False)

DEFAULT_REALM_PATH = Path(__file__).resolve().parent / "seed"
DEFAULT_AGENT_CONFIG_PATH = DEFAULT_REALM_PATH / "agents" / "dm"


@dataclass(frozen=True)
class LLMReply:
    text: str
    response_id: str | None
    tool_traces: list[ToolTrace]
    visible_events: list[VisibleEvent]


def generate_reply(
    messages: Iterable[Message],
    *,
    client: OpenAI | None = None,
    model: str | None = None,
    agent_config_path: Path = DEFAULT_AGENT_CONFIG_PATH,
    workspace_path: Path | None = None,
    turn_file_path: Path | None = None,
    hook: str = "on_message",
    extra_system_messages: list[str] | None = None,
    event_sink: Callable[[str, dict[str, Any]], None] | None = None,
) -> LLMReply:
    scratchpad = {}
    if workspace_path is not None and turn_file_path is not None:
        relative_turn_file = turn_file_path.relative_to(workspace_path).as_posix()
        scratchpad["turn_file_path"] = relative_turn_file
        scratchpad["runtime_instructions"] = (
            "Current turn file: "
            f"`{relative_turn_file}`. Write it with `write_file` before finishing "
            "the turn. It must be markdown with YAML frontmatter containing "
            "`player_intent`, followed by a markdown body. Write and revise this "
            "turn file before emitting visible text or component events. After "
            "the turn file is in place, emit player-visible output with the "
            "agent's available event tools.\n\n"
            "Character creation writes character data and narrative records. "
            "Do not write Python turn scripts. World effects are resolved by "
            "the installed simulation after the character enters play."
        )

    agent_messages = [
        AgentMessage(role=message.role, content=message.body)
        for message in messages
        if message.role in {"user", "assistant", "system"}
    ]
    agent_messages.extend(
        AgentMessage(role="system", content=message)
        for message in extra_system_messages or []
    )

    context = Context(
        messages=agent_messages,
        scratchpad=scratchpad,
        workspace_path=workspace_path,
        event_sink=event_sink,
    )
    agent = load_agent(agent_config_path, context=context)
    provider = OpenAIModelProvider(
        client=client,
        model=model,
    )
    result = agent.run(provider, hook=hook)

    return LLMReply(
        text=result.text,
        response_id=result.provider_response_id,
        tool_traces=list(agent.context.tool_traces),
        visible_events=list(agent.context.visible_events),
    )
