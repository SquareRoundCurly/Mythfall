from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

TURNS_DIR = "turns"
TURN_LOCK_FILE = "turns.lock"
TURN_FILE = "turn.md"
TURN_EVENTS_FILE = "events.jsonl"
TURN_FILE_PLACEHOLDER = """---
player_intent: ""
---

Turn not generated yet.
"""

TurnEventKind = Literal["visible", "debug"]


@dataclass(frozen=True)
class TurnEvent:
    sequence: int
    kind: TurnEventKind
    body: str
    speaker: str | None = None
    role: str | None = None
    label: str | None = None
    event_type: str = "text"
    component: str | None = None
    payload: dict | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_record(self) -> dict:
        return {
            "sequence": self.sequence,
            "kind": self.kind,
            "speaker": self.speaker,
            "role": self.role,
            "label": self.label,
            "event_type": self.event_type,
            "component": self.component,
            "payload": self.payload,
            "body": self.body,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class Turn:
    session_uuid: str
    number: int
    player_message: str
    player_message_id: int | None
    workspace_path: Path
    path: Path
    turn_file_path: Path
    events_file_path: Path
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    events: list[TurnEvent] = field(default_factory=list)

    def emit_visible(
        self,
        *,
        speaker: str,
        body: str,
        event_type: str = "text",
        component: str | None = None,
        payload: dict | None = None,
    ) -> TurnEvent:
        event = TurnEvent(
            sequence=self._next_event_sequence(),
            kind="visible",
            speaker=speaker,
            label=speaker,
            role="assistant",
            event_type=event_type,
            component=component,
            payload=payload,
            body=body,
        )
        self.events.append(event)
        self._append_event(event)
        return event

    def emit_debug(self, *, role: str, label: str, body: str) -> TurnEvent:
        event = TurnEvent(
            sequence=self._next_event_sequence(),
            kind="debug",
            role=role,
            label=label,
            body=body,
        )
        self.events.append(event)
        self._append_event(event)
        return event

    def require_visible_events(self) -> None:
        if not any(event.kind == "visible" for event in self.events):
            raise ValueError("Turn must emit at least one visible event.")

    def require_generated_turn_file(self) -> None:
        content = self.turn_file_path.read_text(encoding="utf-8")
        if not content.strip() or content == TURN_FILE_PLACEHOLDER:
            raise ValueError("Turn must include a generated turn.md file.")

    def truncate_events(self, count: int) -> None:
        self.events = self.events[:count]
        with self.events_file_path.open("w", encoding="utf-8") as events_file:
            for event in self.events:
                json.dump(event.to_record(), events_file, sort_keys=True)
                events_file.write("\n")

    def _next_event_sequence(self) -> int:
        return len(self.events) + 1

    def _append_event(self, event: TurnEvent) -> None:
        with self.events_file_path.open("a", encoding="utf-8") as events_file:
            json.dump(event.to_record(), events_file, sort_keys=True)
            events_file.write("\n")


def begin_turn(
    *,
    session_uuid: str,
    workspace_path: Path,
    player_message: str,
    player_message_id: int | None = None,
) -> Turn:
    turn_path = _create_next_turn_path(workspace_path)

    return Turn(
        session_uuid=session_uuid,
        number=int(turn_path.name),
        player_message=player_message,
        player_message_id=player_message_id,
        workspace_path=workspace_path,
        path=turn_path,
        turn_file_path=turn_path / TURN_FILE,
        events_file_path=turn_path / TURN_EVENTS_FILE,
    )


def _create_next_turn_path(workspace_path: Path) -> Path:
    turns_path = workspace_path / TURNS_DIR
    turns_path.mkdir(parents=True, exist_ok=True)

    lock_path = turns_path / TURN_LOCK_FILE

    with lock_path.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            next_number = _next_turn_number(turns_path)
            turn_path = turns_path / str(next_number)
            turn_path.mkdir()
            _create_required_turn_file(turn_path)
            return turn_path
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _next_turn_number(turns_path: Path) -> int:
    existing_numbers = [
        int(path.name)
        for path in turns_path.iterdir()
        if path.is_dir() and path.name.isdecimal()
    ]

    if not existing_numbers:
        return 1

    return max(existing_numbers) + 1


def _create_required_turn_file(turn_path: Path) -> None:
    turn_file_path = turn_path / TURN_FILE
    _write_text_atomically(turn_file_path, TURN_FILE_PLACEHOLDER)

    events_file_path = turn_path / TURN_EVENTS_FILE
    _write_text_atomically(events_file_path, "")


def _write_text_atomically(path: Path, content: str) -> None:
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as temp_file:
        temp_file.write(content)
        temp_path = Path(temp_file.name)

    temp_path.replace(path)
