"""Bounded structured decisions through Model Gateway, with durable call receipts."""

import json
import os
from pathlib import Path
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from RealmEngine.model_gateway import openai_client
from .simulation.state import ActionError, fingerprint, require

MODEL = "gpt-6-astra"
MAX_OUTPUT_TOKENS = 3000
CALL_TIMEOUT_SECONDS = 90


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Condition(StrictModel):
    kind: Literal["item_taken", "actor_arrived", "actor_departed", "event"]
    target: str | None
    event: Literal["speech", "attack", "take", "give", "drop", "notice"] | None


class Intent(StrictModel):
    kind: Literal["move", "travel", "take", "drop", "equip", "unequip", "give", "use", "speak", "inspect", "check", "attack", "wait", "rest", "work", "idle",
                  "ability", "choose_class", "prepare", "recruit", "dismiss", "order", "short_rest", "long_rest", "end_turn", "reaction", "retreat", "copy_spell", "offer_truce",
                  "dodge", "dash", "disengage", "hide", "stand", "help", "offhand", "climb", "write", "read", "put", "loot", "eat_remains", "traverse", "attune", "refuel"]
    target: str | None
    recipient: str | None
    position: list[int] | None
    text: str | None
    ticks: int | None
    until_hour: int | None
    until: Condition | None
    activity: Literal["watch", "rest", "work"] | None
    stat: Literal["str", "dex", "con", "int", "wis", "cha"] | None
    adjacent: bool | None
    open: bool | None
    ability: str | None = None
    targets: list[str] | None = None
    channel: Literal["speech", "whisper", "telepathy"] | None = None
    language: str | None = None
    skill: str | None = None
    class_name: Literal["fighter", "rogue", "cleric", "wizard"] | None = Field(default=None, alias="class")
    subclass: str | None = None
    skills: list[str] | None = None
    expertise: list[str] | None = None
    style: str | None = None
    spells: list[str] | None = None
    cantrips: list[str] | None = None
    abilities: list[str] | None = None
    slot: int | str | None = None
    slots: list[int] | None = None
    hit_dice: list[str] | None = None
    exclude: list[str] | None = None
    allocations: list[int] | None = None
    command: str | None = None
    condition: str | None = None
    item: str | None = None
    object: str | None = None
    nonlethal: bool | None = None

    def intent(self):
        return self.model_dump(exclude_none=True, by_alias=True)


class Interpretation(StrictModel):
    mode: Literal["action", "dialogue", "answer", "refuse", "clarify", "tools"]
    action: Intent | None
    target: str | None
    text: str = Field(max_length=1200)
    operations_json: str | None = Field(default=None, max_length=18000)
    handoffs: list[str] = Field(default_factory=list, max_length=2)
    channel: Literal["speech", "whisper", "telepathy"] | None = None


class NPCDecision(StrictModel):
    speech: str = Field(max_length=1200)
    actions: list[Intent] = Field(max_length=12)
    reason: str = Field(min_length=1, max_length=800)
    promise: str | None
    horizon_ticks: int = Field(ge=1, le=600)
    join_party: bool = False
    leave_party: bool = False


class CombatIntent(StrictModel):
    kind: Literal["move", "attack", "offhand", "ability", "use", "equip", "unequip", "speak", "dodge", "dash", "disengage", "hide", "stand", "help", "end_turn", "retreat", "reaction", "offer_truce"]
    target: str | None = None
    position: list[int] | None = None
    ability: str | None = None
    slot: int | str | None = None
    text: str | None = None
    command: str | None = None
    condition: str | None = None
    targets: list[str] | None = None
    exclude: list[str] | None = None
    def intent(self):
        return self.model_dump(exclude_none=True)


class CombatDecision(StrictModel):
    actions: list[CombatIntent] = Field(min_length=1, max_length=12)
    reason: str = Field(min_length=1, max_length=800)


def strict_schema(schema):
    """All properties are required on the wire; nullable fields express absence.

    Local defaults retain compatibility with recorded decisions from older saves.
    """
    result = schema.model_json_schema(by_alias=True)
    def visit(node):
        if isinstance(node, dict):
            node.pop("default", None)
            if node.get("type") == "object":
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)
    visit(result)
    return result


def _atomic_json(path, data):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def decide(workspace, operation_id, schema, instructions, observation, *, client=None):
    """Call at most once per decision identity; uncertain outcomes need a new action.

    The runtime's world lock covers callers. Completed outputs can be replayed
    after interruption without another request. This journal is session data,
    not a tool surface exposed to the player interpreter or NPC.
    """
    directory = Path(workspace) / "state" / "model_calls"
    directory.mkdir(parents=True, exist_ok=True)
    key = fingerprint({"operation": operation_id})
    path = directory / f"{key}.json"
    digest = fingerprint({"model": MODEL, "schema": schema.__name__, "instructions": instructions, "input": observation})
    if path.exists():
        record = json.loads(path.read_text())
        require(record["input_hash"] == digest, "That decision belongs to an earlier world observation. Submit a new action.")
        require(record["status"] == "completed", "The previous model call did not finish reliably. Time is paused; submit a new action to try again.")
        return schema.model_validate(record["output"]), record["receipt"]
    record = {"operation_id": operation_id, "input_hash": digest, "model": MODEL,
              "schema": schema.__name__, "status": "submitted", "started_at": time.time()}
    _atomic_json(path, record)
    started = time.monotonic()
    try:
        response = (client or openai_client()).responses.create(
            model=MODEL, reasoning={"effort": "medium"}, max_output_tokens=MAX_OUTPUT_TOKENS,
            instructions=instructions, input=json.dumps(observation, ensure_ascii=False),
            text={"format": {"type": "json_schema", "name": schema.__name__,
                             "schema": strict_schema(schema), "strict": True}},
            timeout=CALL_TIMEOUT_SECONDS,
        )
        if getattr(response, "status", "completed") != "completed":
            raise ValueError("The model reached its output limit.")
        parsed = schema.model_validate_json(response.output_text)
        usage = getattr(response, "usage", None)
        receipt = {"model": MODEL, "response_id": response.id, "elapsed_seconds": round(time.monotonic() - started, 3),
                   "usage": usage.model_dump() if usage else None}
        record.update(status="completed", output=parsed.model_dump(), receipt=receipt)
        _atomic_json(path, record)
        return parsed, receipt
    except Exception as error:
        # Provider errors can contain internal URLs; retain a safe type only.
        record.update(status="failed_or_uncertain", error_type=type(error).__name__,
                      elapsed_seconds=round(time.monotonic() - started, 3))
        _atomic_json(path, record)
        raise ActionError("The conversation could not finish. World time is paused; you can try a new action.") from error
