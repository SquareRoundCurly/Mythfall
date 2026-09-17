from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from .context import Context
from .tools import FunctionTool, ToolResult, ToolSpec
from mythfall.realms import RealmValidationError, load_realm, validate_realm_write


DEFAULT_MAX_READ_BYTES = 20_000
DEFAULT_MAX_SEARCH_FILE_BYTES = 200_000
DEFAULT_MAX_RESULTS = 50


class FileToolError(ValueError):
    pass


def _workspace_root(context: Context) -> Path:
    if context.workspace_path is None:
        raise FileToolError("Context does not have a workspace path.")

    root = context.workspace_path.resolve()
    if not root.exists() or not root.is_dir():
        raise FileToolError("Workspace path does not exist or is not a directory.")

    return root


def _resolve_workspace_path(
    context: Context,
    path: str | None,
    *,
    must_exist: bool,
) -> Path:
    relative_path = path or "."
    requested_path = Path(relative_path)

    if requested_path.is_absolute():
        raise FileToolError("Absolute paths are not allowed.")

    if ".." in requested_path.parts:
        raise FileToolError("Parent path segments are not allowed.")

    root = _workspace_root(context)
    resolved_path = (root / requested_path).resolve()

    if resolved_path != root and root not in resolved_path.parents:
        raise FileToolError("Path escapes the workspace.")

    if must_exist and not resolved_path.exists():
        raise FileToolError(f"Path does not exist: {relative_path}")

    return resolved_path


def _relative_to_workspace(context: Context, path: Path) -> str:
    return path.relative_to(_workspace_root(context)).as_posix()


def _read_text(path: Path, *, max_bytes: int) -> str:
    if not path.is_file():
        raise FileToolError("Path is not a file.")

    raw = path.read_bytes()
    if len(raw) > max_bytes:
        raise FileToolError(f"File is too large to read ({len(raw)} bytes).")

    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise FileToolError("File is not valid UTF-8 text.") from error


def list_files(context: Context, arguments: dict[str, Any]) -> ToolResult:
    path = _resolve_workspace_path(
        context,
        arguments.get("path"),
        must_exist=True,
    )
    recursive = bool(arguments.get("recursive", False))
    max_entries = int(arguments.get("max_entries", 200))

    if max_entries < 1:
        raise FileToolError("max_entries must be at least 1.")

    if path.is_file():
        files = [_relative_to_workspace(context, path)]
    elif recursive:
        files = [
            _relative_to_workspace(context, child)
            for child in sorted(path.rglob("*"))
            if child.is_file() and not child.is_symlink()
        ]
    else:
        files = [
            f"{_relative_to_workspace(context, child)}/" if child.is_dir()
            else _relative_to_workspace(context, child)
            for child in sorted(path.iterdir())
            if not child.is_symlink()
        ]

    limited_files = files[:max_entries]
    content = "\n".join(limited_files) if limited_files else "(empty)"
    return ToolResult(
        content=content,
        data={
            "files": limited_files,
            "truncated": len(files) > len(limited_files),
        },
    )


def read_file(context: Context, arguments: dict[str, Any]) -> ToolResult:
    path = _resolve_workspace_path(
        context,
        arguments.get("path"),
        must_exist=True,
    )
    max_bytes = int(arguments.get("max_bytes", DEFAULT_MAX_READ_BYTES))
    content = _read_text(path, max_bytes=max_bytes)

    return ToolResult(
        content=content,
        data={
            "path": _relative_to_workspace(context, path),
            "bytes": len(content.encode("utf-8")),
        },
    )


def search_files(context: Context, arguments: dict[str, Any]) -> ToolResult:
    query = str(arguments.get("query", ""))
    if not query:
        raise FileToolError("query is required.")

    path = _resolve_workspace_path(
        context,
        arguments.get("path"),
        must_exist=True,
    )
    max_results = int(arguments.get("max_results", DEFAULT_MAX_RESULTS))
    max_file_bytes = int(
        arguments.get("max_file_bytes", DEFAULT_MAX_SEARCH_FILE_BYTES),
    )

    if max_results < 1:
        raise FileToolError("max_results must be at least 1.")

    candidates: Iterable[Path]
    if path.is_file():
        candidates = [path]
    else:
        candidates = sorted(
            child
            for child in path.rglob("*")
            if child.is_file() and not child.is_symlink()
        )

    matches: list[dict[str, Any]] = []
    for candidate in candidates:
        try:
            text = _read_text(candidate, max_bytes=max_file_bytes)
        except FileToolError:
            continue

        for line_number, line in enumerate(text.splitlines(), start=1):
            if query.lower() not in line.lower():
                continue

            matches.append(
                {
                    "path": _relative_to_workspace(context, candidate),
                    "line": line_number,
                    "text": line,
                },
            )

            if len(matches) >= max_results:
                break

        if len(matches) >= max_results:
            break

    content = "\n".join(
        f"{match['path']}:{match['line']}: {match['text']}"
        for match in matches
    )
    return ToolResult(
        content=content or "(no matches)",
        data={
            "matches": matches,
            "truncated": len(matches) >= max_results,
        },
    )


def write_file(context: Context, arguments: dict[str, Any]) -> ToolResult:
    if "path" not in arguments:
        raise FileToolError("path is required.")

    if "content" not in arguments:
        raise FileToolError("content is required.")

    path = _resolve_workspace_path(
        context,
        str(arguments["path"]),
        must_exist=False,
    )
    overwrite = bool(arguments.get("overwrite", True))

    if path.exists() and not overwrite:
        raise FileToolError(f"Path already exists: {arguments['path']}")

    relative_path = path.relative_to(_workspace_root(context))
    _validate_turn_write(context, relative_path)
    _validate_player_stats_write(context, relative_path, str(arguments["content"]))
    content = _preserve_locked_player_stats(
        relative_path,
        str(arguments["content"]),
        existing_content=path.read_text(encoding="utf-8") if path.exists() else None,
    )

    validation_error: str | None = None
    try:
        validate_realm_write(
            load_realm(_workspace_root(context)),
            relative_path,
            content=content,
            exists=path.exists(),
        )
    except RealmValidationError as error:
        validation_error = str(error)
        if not _can_save_invalid_character_draft(context, relative_path):
            raise FileToolError(validation_error) from error

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    relative_workspace_path = _relative_to_workspace(context, path)
    _publish_workspace_changed(context, relative_workspace_path)

    if validation_error is not None:
        return ToolResult(
            content=(
                f"Wrote draft {relative_workspace_path}, but it is "
                f"not ready for play. Validation error: {validation_error}"
            ),
            data={
                "path": relative_workspace_path,
                "bytes": len(content.encode("utf-8")),
                "valid": False,
                "validation_error": validation_error,
            },
        )

    return ToolResult(
        content=f"Wrote {relative_workspace_path}.",
        data={
            "path": relative_workspace_path,
            "bytes": len(content.encode("utf-8")),
            "valid": True,
        },
    )


def _publish_workspace_changed(context: Context, path: str) -> None:
    context.publish_event(
        "workspace.changed",
        {
            "path": path,
            "kind": "file",
            "operation": "write",
        },
    )


def _can_save_invalid_character_draft(context: Context, relative_path: Path) -> bool:
    return (
        context.scratchpad.get("agent_id") == "character_creator"
        and relative_path.as_posix() == "characters/player.md"
    )


def _validate_player_stats_write(
    context: Context,
    relative_path: Path,
    content: str,
) -> None:
    if relative_path.as_posix() != "characters/player.md":
        return

    frontmatter, _ = _parse_frontmatter(content)
    if "stats" not in frontmatter:
        return

    existing_path = _workspace_root(context) / relative_path
    if existing_path.exists():
        existing_frontmatter, _ = _parse_frontmatter(
            existing_path.read_text(encoding="utf-8"),
        )
        if existing_frontmatter.get("stats_locked") is True:
            return

    raise FileToolError(
        "Player stats can only be set by the stat assignment component. "
        "Write the character draft without frontmatter.stats until stats are assigned.",
    )


def _preserve_locked_player_stats(
    relative_path: Path,
    content: str,
    *,
    existing_content: str | None,
) -> str:
    if relative_path.as_posix() != "characters/player.md" or not existing_content:
        return content

    existing_frontmatter, _ = _parse_frontmatter(existing_content)
    if existing_frontmatter.get("stats_locked") is not True:
        return content

    existing_stats = existing_frontmatter.get("stats")
    if not isinstance(existing_stats, dict):
        return content

    next_frontmatter, next_body = _parse_frontmatter(content)
    next_frontmatter["stats"] = existing_stats
    next_frontmatter["stats_locked"] = True
    next_frontmatter["stats_source"] = existing_frontmatter.get(
        "stats_source",
        "stat_assignment",
    )

    return (
        "---\n"
        f"{yaml.safe_dump(next_frontmatter, sort_keys=False)}"
        "---"
        f"{next_body}"
    )


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    if not content.startswith("---\n"):
        return {}, content

    try:
        _, frontmatter_text, body = content.split("---", 2)
    except ValueError:
        return {}, content

    frontmatter = yaml.safe_load(frontmatter_text) or {}
    if not isinstance(frontmatter, dict):
        return {}, body

    return frontmatter, body


def _validate_turn_write(context: Context, relative_path: Path) -> None:
    if not relative_path.parts or relative_path.parts[0] != "turns":
        return

    current_turn_file = context.scratchpad.get("turn_file_path")
    if not current_turn_file:
        raise FileToolError("Turn file writes are only available during a turn.")

    current_turn_path = Path(str(current_turn_file))
    allowed_paths = {
        current_turn_path.as_posix(),
        (current_turn_path.parent / "script.py").as_posix(),
    }

    if relative_path.as_posix() not in allowed_paths:
        allowed = ", ".join(sorted(allowed_paths))
        raise FileToolError(f"Only current turn files can be written: {allowed}")


def filesystem_tools() -> dict[str, FunctionTool]:
    return {
        "list_files": FunctionTool(
            spec=ToolSpec(
                name="list_files",
                description="List files or directories inside the realm workspace.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "recursive": {"type": "boolean"},
                        "max_entries": {"type": "integer"},
                    },
                },
            ),
            handler=list_files,
        ),
        "read_file": FunctionTool(
            spec=ToolSpec(
                name="read_file",
                description="Read a UTF-8 text file inside the realm workspace.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "max_bytes": {"type": "integer"},
                    },
                    "required": ["path"],
                },
            ),
            handler=read_file,
        ),
        "search_files": FunctionTool(
            spec=ToolSpec(
                name="search_files",
                description="Search UTF-8 text files inside the realm workspace.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "path": {"type": "string"},
                        "max_results": {"type": "integer"},
                        "max_file_bytes": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            ),
            handler=search_files,
        ),
        "write_file": FunctionTool(
            spec=ToolSpec(
                name="write_file",
                description="Write a UTF-8 text file inside the realm workspace.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                        "overwrite": {"type": "boolean"},
                    },
                    "required": ["path", "content"],
                },
            ),
            handler=write_file,
        ),
    }
