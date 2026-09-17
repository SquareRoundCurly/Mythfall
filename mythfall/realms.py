import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from RealmEngine.modules import RealmStateDefinition


REALM_MANIFEST = "realm.json"


class RealmValidationError(ValueError):
    pass


@dataclass(frozen=True)
class RealmFileFormat:
    extension: str
    kind: str
    frontmatter: dict[str, Any]
    body: dict[str, Any]


@dataclass(frozen=True)
class RealmTemplatePermissions:
    read: bool
    write: bool
    allow_new_files: bool
    allow_new_folders: bool


@dataclass(frozen=True)
class RealmTemplate:
    id: str
    folder: str
    permissions: RealmTemplatePermissions
    file_formats: list[RealmFileFormat]

    def format_for_path(self, path: Path) -> RealmFileFormat | None:
        for file_format in self.file_formats:
            if path.suffix == file_format.extension:
                return file_format

        return None


@dataclass(frozen=True)
class Realm:
    id: str
    name: str
    version: int
    path: Path
    description: str = ""
    templates: dict[str, RealmTemplate] | None = None
    filesystem: dict[str, Any] | None = None
    initial_state: str = "play"
    states: dict[str, RealmStateDefinition] | None = None


def load_realm(path: Path) -> Realm:
    manifest_path = path / REALM_MANIFEST
    with manifest_path.open(encoding="utf-8") as manifest_file:
        manifest: dict[str, Any] = json.load(manifest_file)

    return Realm(
        id=str(manifest["id"]),
        name=str(manifest["name"]),
        version=int(manifest["version"]),
        description=str(manifest.get("description", "")),
        path=path,
        templates=_load_templates(path, manifest),
        filesystem=dict(manifest.get("filesystem", {})),
        initial_state=str(manifest.get("initial_state", "play")),
        states=_parse_state_definitions(manifest),
    )


def maybe_load_realm(path: Path) -> Realm | None:
    manifest_path = path / REALM_MANIFEST
    if not manifest_path.exists():
        return None

    return load_realm(path)


def copy_realm_seed(
    realm: Realm,
    target_path: Path,
    *,
    overwrite: bool = False,
) -> None:
    target_path.mkdir(parents=True, exist_ok=True)

    for source_path in sorted(realm.path.rglob("*")):
        relative_path = source_path.relative_to(realm.path)
        target_child = target_path / relative_path

        if source_path.is_dir():
            target_child.mkdir(parents=True, exist_ok=True)
            continue

        if target_child.exists() and not overwrite and not _is_seed_managed_path(relative_path):
            continue

        target_child.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_child)


def _is_seed_managed_path(relative_path: Path) -> bool:
    return relative_path.name == REALM_MANIFEST or relative_path.parts[0] in {
        "agents",
        "templates",
    }


def validate_realm_write(
    realm: Realm,
    relative_path: Path,
    *,
    content: str,
    exists: bool,
) -> None:
    if relative_path.is_absolute():
        raise RealmValidationError("Realm paths must be relative.")

    if not relative_path.parts:
        raise RealmValidationError("Realm path is required.")

    if len(relative_path.parts) == 1:
        if not _filesystem_bool(realm, "allow_root_writes", False):
            raise RealmValidationError("Writing files at the realm root is not allowed.")

    relative_path_text = relative_path.as_posix()
    readonly_paths = set(_filesystem_list(realm, "readonly_paths"))
    if relative_path_text in readonly_paths:
        raise RealmValidationError(f"Path is read-only: {relative_path_text}")

    folder = relative_path.parts[0]
    template = (realm.templates or {}).get(folder)
    if template is None:
        if _filesystem_bool(realm, "allow_unknown_top_level_folders", False):
            return

        raise RealmValidationError(f"Unknown top-level realm folder: {folder}")

    if not template.permissions.write:
        raise RealmValidationError(f"Folder is read-only: {folder}")

    if not exists and not template.permissions.allow_new_files:
        raise RealmValidationError(f"New files are not allowed in folder: {folder}")

    if len(relative_path.parts) > 2 and not template.permissions.allow_new_folders:
        raise RealmValidationError(f"New nested folders are not allowed in folder: {folder}")

    file_format = template.format_for_path(relative_path)
    if file_format is None:
        extensions = ", ".join(
            sorted(file_format.extension for file_format in template.file_formats),
        )
        raise RealmValidationError(
            f"Invalid file extension for {folder}. Expected one of: {extensions}",
        )

    validate_realm_file_content(file_format, content, realm=realm, relative_path=relative_path)


def validate_realm_file_content(
    file_format: RealmFileFormat,
    content: str,
    *,
    realm: Realm | None = None,
    relative_path: Path | None = None,
) -> None:
    if file_format.kind == "json":
        json.loads(content)
        return

    if file_format.kind == "markdown":
        if not content.strip():
            raise RealmValidationError("Markdown file body must not be empty.")
        return

    if file_format.kind == "markdown_frontmatter":
        frontmatter, body = _parse_markdown_frontmatter(content)
        _validate_frontmatter(frontmatter, file_format.frontmatter)
        _validate_realm_references(
            realm,
            relative_path,
            frontmatter,
        )

        if file_format.body.get("required", False) and not body.strip():
            raise RealmValidationError("Markdown body is required.")
        return

    raise RealmValidationError(f"Unsupported file format kind: {file_format.kind}")


def _load_templates(path: Path, manifest: dict[str, Any]) -> dict[str, RealmTemplate]:
    templates: dict[str, RealmTemplate] = {}

    for template_path_text in manifest.get("templates", []):
        template_path = path / str(template_path_text)
        with template_path.open(encoding="utf-8") as template_file:
            template_data: dict[str, Any] = json.load(template_file)

        template = _parse_template(template_data)
        templates[template.folder] = template

    return templates


def _parse_template(template_data: dict[str, Any]) -> RealmTemplate:
    permissions_data = template_data.get("permissions", {})
    return RealmTemplate(
        id=str(template_data["id"]),
        folder=str(template_data["folder"]),
        permissions=RealmTemplatePermissions(
            read=bool(permissions_data.get("read", True)),
            write=bool(permissions_data.get("write", False)),
            allow_new_files=bool(permissions_data.get("allow_new_files", False)),
            allow_new_folders=bool(permissions_data.get("allow_new_folders", False)),
        ),
        file_formats=[
            RealmFileFormat(
                extension=str(file_format["extension"]),
                kind=str(file_format["kind"]),
                frontmatter=dict(file_format.get("frontmatter", {})),
                body=dict(file_format.get("body", {})),
            )
            for file_format in template_data.get("file_formats", [])
        ],
    )


def _parse_state_definitions(
    manifest: dict[str, Any],
) -> dict[str, RealmStateDefinition]:
    states_data = manifest.get("states", {})
    if not isinstance(states_data, dict):
        return {}

    states: dict[str, RealmStateDefinition] = {}
    for state_id, state_data in states_data.items():
        if not isinstance(state_data, dict):
            continue

        next_states = state_data.get("next", [])
        if not isinstance(next_states, list):
            next_states = []

        agent = state_data.get("agent")
        initial_message = state_data.get("initial_message")
        states[str(state_id)] = RealmStateDefinition(
            id=str(state_id),
            agent=str(agent) if agent is not None else None,
            initial_message=(
                str(initial_message)
                if initial_message is not None
                else None
            ),
            next=[str(next_state) for next_state in next_states],
        )

    return states


def _filesystem_bool(realm: Realm, key: str, default: bool) -> bool:
    return bool((realm.filesystem or {}).get(key, default))


def _filesystem_list(realm: Realm, key: str) -> list[str]:
    value = (realm.filesystem or {}).get(key, [])
    if not isinstance(value, list):
        return []

    return [str(item) for item in value]


def _parse_markdown_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    if not content.startswith("---\n"):
        raise RealmValidationError("Markdown file must start with YAML frontmatter.")

    try:
        _, frontmatter_text, body = content.split("---", 2)
    except ValueError as error:
        raise RealmValidationError("Markdown file must close YAML frontmatter.") from error

    parsed_frontmatter = yaml.safe_load(frontmatter_text) or {}
    if not isinstance(parsed_frontmatter, dict):
        raise RealmValidationError("Markdown frontmatter must be a mapping.")

    return parsed_frontmatter, body


def _validate_frontmatter(
    frontmatter: dict[str, Any],
    schema: dict[str, Any],
    *,
    path: str = "frontmatter",
) -> None:
    missing_keys = [
        f"{path}.{key}"
        for key in schema.get("required", [])
        if key not in frontmatter
    ]
    if missing_keys:
        raise RealmValidationError(
            f"Missing required fields: {', '.join(missing_keys)}",
        )

    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return

    for key, property_schema in properties.items():
        if key not in frontmatter or not isinstance(property_schema, dict):
            continue

        value = frontmatter[key]
        expected_const = property_schema.get("const")
        if expected_const is not None and value != expected_const:
            raise RealmValidationError(
                f"Expected {path}.{key} to be {expected_const!r}.",
            )

        expected_type = property_schema.get("type")
        if expected_type is not None and not _matches_type(value, expected_type):
            raise RealmValidationError(f"Expected {path}.{key} to be {expected_type}.")

        _validate_frontmatter(
            value if isinstance(value, dict) else {},
            property_schema,
            path=f"{path}.{key}",
        )


def _validate_realm_references(
    realm: Realm | None,
    relative_path: Path | None,
    frontmatter: dict[str, Any],
) -> None:
    if realm is None or relative_path is None:
        return

    if relative_path.parts[0] == "characters":
        _validate_location_reference(
            realm,
            frontmatter.get("location"),
            label="Character location",
        )
        return

    if relative_path.parts[0] == "locations":
        location_id = _validate_location_reference(
            realm,
            frontmatter.get("id"),
            label="Location id",
        )
        if location_id != relative_path.as_posix():
            raise RealmValidationError(
                "Location id must match the location file path.",
            )

        parent = frontmatter.get("parent")
        if parent is not None:
            _validate_location_reference(
                realm,
                parent,
                label="Location parent",
                allow_directory=True,
            )

        exits = frontmatter.get("exits", {})
        if isinstance(exits, dict):
            for direction, destination in exits.items():
                _validate_location_reference(
                    realm,
                    destination,
                    label=f"Location exit {direction}",
                )
        return

    if relative_path.parts[0] == "quests":
        starts_at = frontmatter.get("starts_at")
        if starts_at is not None:
            _validate_location_reference(
                realm,
                starts_at,
                label="Quest starts_at",
            )

        location_refs = frontmatter.get("location_refs", [])
        if isinstance(location_refs, list):
            for index, location_ref in enumerate(location_refs):
                _validate_location_reference(
                    realm,
                    location_ref,
                    label=f"Quest location_refs[{index}]",
                )


def _validate_location_reference(
    realm: Realm,
    location: Any,
    *,
    label: str,
    allow_directory: bool = False,
) -> str:
    if not isinstance(location, str):
        raise RealmValidationError(f"Expected {label} to be a string.")

    location_path = Path(location)
    if location_path.is_absolute() or ".." in location_path.parts:
        raise RealmValidationError(f"{label} must be a relative realm path.")

    if not location_path.parts or location_path.parts[0] != "locations":
        raise RealmValidationError(
            f"{label} must be a path under locations/.",
        )

    if not allow_directory and location_path.suffix != ".md":
        raise RealmValidationError(
            f"{label} must be a path like locations/.../<name>.md.",
        )

    if allow_directory and location_path.suffix not in {"", ".md"}:
        raise RealmValidationError(
            f"{label} must be a locations/ directory or markdown file path.",
        )

    realm_path = realm.path.resolve()
    resolved_location_path = (realm.path / location_path).resolve()
    if (
        resolved_location_path != realm_path
        and realm_path not in resolved_location_path.parents
    ):
        raise RealmValidationError(f"{label} escapes the realm.")

    if allow_directory:
        exists = resolved_location_path.is_dir() or resolved_location_path.is_file()
    else:
        exists = resolved_location_path.is_file()

    if not exists:
        raise RealmValidationError(f"{label} does not exist: {location}")

    return location


def _matches_type(value: Any, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)

    if expected_type == "array":
        return isinstance(value, list)

    if expected_type == "string":
        return isinstance(value, str)

    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)

    if expected_type == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)

    if expected_type == "boolean":
        return isinstance(value, bool)

    return True
