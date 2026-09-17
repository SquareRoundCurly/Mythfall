from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import yaml

from mythfall.realms import RealmValidationError, load_realm, validate_realm_write
from mythfall.turns import Turn


SCRIPT_FILE = "script.py"


class TurnScriptError(ValueError):
    pass


@dataclass
class Character:
    id: str
    name: str
    path: Path
    workspace_path: Path
    is_player: bool = False

    @classmethod
    def load_player(cls, workspace_path: Path) -> "Character":
        path = workspace_path / "characters" / "player.md"
        frontmatter, _ = _read_character_file(path)
        return cls(
            id=str(frontmatter.get("id") or "char.player"),
            name=str(frontmatter.get("name") or "Player"),
            path=path,
            workspace_path=workspace_path,
            is_player=True,
        )

    def say(self, text: str) -> None:
        _runtime().emit_character_speech(self, text)

    def move(self, location: str) -> None:
        _runtime().move_character(self, location)


@dataclass
class TurnScriptRuntime:
    turn: Turn

    @property
    def workspace_path(self) -> Path:
        return self.turn.workspace_path

    def narrate(self, text: str) -> None:
        body = _clean_text(text, field="narration")
        self.turn.emit_visible(speaker="DM", body=body)

    def say(self, speaker: str, text: str) -> None:
        speaker_text = _clean_text(speaker, field="speaker")
        body = _clean_text(text, field="speech")
        self.turn.emit_visible(speaker=speaker_text, body=body)

    def emit_character_speech(self, character: Character, text: str) -> None:
        body = _clean_text(text, field="speech")
        self.turn.emit_visible(
            speaker=character.name,
            body=body,
            event_type="character_speech",
            payload={
                "character_id": character.id,
                "character_path": character.path.relative_to(
                    self.workspace_path,
                ).as_posix(),
                "is_player": character.is_player,
            },
        )

    def move_character(self, character: Character, location: str) -> None:
        frontmatter, body = _read_character_file(character.path)
        location_path = _validate_location_path(self.workspace_path, location)
        frontmatter["location"] = location_path.as_posix()
        content = _format_frontmatter_file(frontmatter, body)
        relative_path = character.path.relative_to(self.workspace_path)

        try:
            validate_realm_write(
                load_realm(self.workspace_path),
                relative_path,
                content=content,
                exists=True,
            )
        except RealmValidationError as error:
            raise TurnScriptError(
                f"Character update failed validation: {error}",
            ) from error

        _write_text_atomically(character.path, content)
        character.path = self.workspace_path / relative_path
        self.turn.emit_visible(
            speaker=character.name,
            body=f"Moves to `{location_path.as_posix()}`.",
            event_type="character_move",
            payload={
                "character_id": character.id,
                "character_path": relative_path.as_posix(),
                "location": location_path.as_posix(),
                "is_player": character.is_player,
            },
        )


_CURRENT_RUNTIME: TurnScriptRuntime | None = None


def run_turn_script(turn: Turn) -> bool:
    script_path = turn.path / SCRIPT_FILE
    if not script_path.exists():
        return False

    source = script_path.read_text(encoding="utf-8")
    if not source.strip():
        raise TurnScriptError("Turn script exists but is empty.")

    runtime = TurnScriptRuntime(turn=turn)
    player = Character.load_player(turn.workspace_path)
    globals_ = {
        "__builtins__": {
            "False": False,
            "None": None,
            "True": True,
        },
        "narrate": runtime.narrate,
        "player": player,
        "say": runtime.say,
        "turn": runtime,
    }

    global _CURRENT_RUNTIME
    previous_runtime = _CURRENT_RUNTIME
    _CURRENT_RUNTIME = runtime
    try:
        exec(compile(source, str(script_path), "exec"), globals_, {})
    except TurnScriptError:
        raise
    except Exception as error:
        raise TurnScriptError(f"Turn script failed: {error}") from error
    finally:
        _CURRENT_RUNTIME = previous_runtime

    return True


def _runtime() -> TurnScriptRuntime:
    if _CURRENT_RUNTIME is None:
        raise TurnScriptError("Character methods can only run inside a turn script.")

    return _CURRENT_RUNTIME


def _validate_location_path(workspace_path: Path, location: str) -> Path:
    location_text = _clean_text(location, field="location")
    relative_path = Path(location_text)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise TurnScriptError("Location must be a relative realm path.")

    if not relative_path.parts or relative_path.parts[0] != "locations":
        raise TurnScriptError("Location must be under locations/.")

    if relative_path.suffix != ".md":
        raise TurnScriptError("Location must be a markdown file.")

    path = workspace_path / relative_path
    if not path.exists() or not path.is_file():
        raise TurnScriptError(
            "Location does not exist. The DM must inspect locations and use an "
            f"exact locations/**/*.md path: {location_text}",
        )

    return relative_path


def _read_character_file(path: Path) -> tuple[dict[str, Any], str]:
    if not path.exists() or not path.is_file():
        raise TurnScriptError(f"Character file does not exist: {path}")

    content = path.read_text(encoding="utf-8")
    if not content.startswith("---\n"):
        raise TurnScriptError(f"Character file is missing frontmatter: {path}")

    try:
        _, frontmatter_text, body = content.split("---", 2)
    except ValueError as error:
        raise TurnScriptError(
            f"Character file frontmatter is not closed: {path}",
        ) from error

    frontmatter = yaml.safe_load(frontmatter_text) or {}
    if not isinstance(frontmatter, dict):
        raise TurnScriptError(f"Character frontmatter must be a mapping: {path}")

    return frontmatter, body


def _format_frontmatter_file(frontmatter: dict[str, Any], body: str) -> str:
    return (
        "---\n"
        f"{yaml.safe_dump(frontmatter, sort_keys=False)}"
        "---"
        f"{body}"
    )


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


def _clean_text(value: str, *, field: str) -> str:
    text = str(value).strip()
    if not text:
        raise TurnScriptError(f"{field} is required.")

    return text
