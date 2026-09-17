import json
import os
from typing import Any

from openai import OpenAI

from RealmEngine.model_gateway import openai_client

from .agent import Agent
from .providers import AgentResult, ModelProvider, ToolCall
from .tools import Tool


DEFAULT_MODEL = "gpt-5.4-mini"


class OpenAIModelProvider(ModelProvider):
    def __init__(
        self,
        *,
        client: OpenAI | None = None,
        model: str | None = None,
    ) -> None:
        self.client = client or openai_client()
        self.model = model

    def run(self, agent: Agent, tools: list[Tool]) -> AgentResult:
        instructions = agent.instructions
        runtime_instructions = agent.context.scratchpad.get("runtime_instructions")
        if runtime_instructions:
            instructions = f"{instructions}\n\nRuntime turn instructions:\n{runtime_instructions}"

        create_args: dict[str, Any] = {
            "model": self.model
            or agent.config.model
            or os.environ.get("OPENAI_MODEL", DEFAULT_MODEL),
            "instructions": instructions,
        }

        if tools:
            create_args["tools"] = [
                {
                    "type": "function",
                    "name": tool.spec.name,
                    "description": tool.spec.description,
                    "parameters": tool.spec.input_schema,
                    "strict": False,
                }
                for tool in tools
            ]

        previous_response_id = agent.context.scratchpad.get(
            "openai_previous_response_id",
        )

        if previous_response_id and agent.context.pending_tool_results:
            create_args["previous_response_id"] = previous_response_id
            create_args["input"] = [
                {
                    "type": "function_call_output",
                    "call_id": tool_result.call_id,
                    "output": tool_result.content,
                }
                for tool_result in agent.context.pending_tool_results
            ]
        else:
            create_args["input"] = [
                {
                    "role": message.role,
                    "content": message.content,
                }
                for message in agent.context.messages
                if message.role in {"user", "assistant", "system"}
            ]

        response = self.client.responses.create(**create_args)
        agent.context.scratchpad["openai_previous_response_id"] = response.id

        text = response.output_text.strip()
        tool_calls = _extract_tool_calls(response)

        if (
            not text
            and not tool_calls
            and not agent.context.pending_tool_results
        ):
            raise RuntimeError("Model response did not include output text.")

        return AgentResult(
            text=text,
            tool_calls=tool_calls,
            provider_response_id=response.id,
        )


def _extract_tool_calls(response: Any) -> list[ToolCall]:
    tool_calls: list[ToolCall] = []

    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", None) != "function_call":
            continue

        arguments = _load_arguments(getattr(item, "arguments", "{}"))
        tool_calls.append(
            ToolCall(
                name=getattr(item, "name"),
                arguments=arguments,
                id=getattr(item, "call_id", None) or getattr(item, "id", None),
            ),
        )

    return tool_calls


def _load_arguments(raw_arguments: Any) -> dict[str, Any]:
    if isinstance(raw_arguments, dict):
        return raw_arguments

    if not raw_arguments:
        return {}

    try:
        parsed_arguments = json.loads(raw_arguments)
    except json.JSONDecodeError:
        return {}

    if not isinstance(parsed_arguments, dict):
        return {}

    return parsed_arguments
