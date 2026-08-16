from __future__ import annotations

import platform
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ManifestError(ValueError):
    pass


SUPPORTED_PLATFORMS = {"linux", "darwin", "windows"}


def current_platform() -> str:
    value = platform.system().casefold()
    return {"linux": "linux", "darwin": "darwin", "windows": "windows"}.get(value, value)


def platform_value(value: Any, label: str) -> Any:
    if not isinstance(value, dict):
        return value
    invalid = set(value) - SUPPORTED_PLATFORMS - {"default"}
    if invalid:
        raise ManifestError(f"{label} has unsupported platform keys: {', '.join(sorted(invalid))}")
    return value.get(current_platform(), value.get("default"))


@dataclass(frozen=True)
class Manifest:
    name: str
    description: str
    repo: str
    tags: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()
    setup: tuple[str, ...] = ()
    update: tuple[str, ...] = ()
    remove: tuple[str, ...] = ()
    commands: dict[str, str] = field(default_factory=dict)
    command: str | None = None
    schema: int = 1
    homepage: str | None = None

    @classmethod
    def from_text(cls, text: str, repo: str = "") -> Manifest:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ManifestError(f"invalid YAML: {exc}") from exc
        if not isinstance(data, dict):
            raise ManifestError("manifest must be a YAML object")
        return cls.from_dict(data, repo)

    @classmethod
    def from_path(cls, path: Path, repo: str = "") -> Manifest:
        return cls.from_text(path.read_text(encoding="utf-8"), repo)

    @classmethod
    def from_dict(cls, data: dict[str, Any], repo: str = "") -> Manifest:
        schema = data.get("schema", 1)
        if schema != 1:
            raise ManifestError(f"unsupported schema {schema!r}; expected 1")
        name = data.get("name")
        description = data.get("description")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
            raise ManifestError("name must contain only letters, numbers, '.', '_' and '-'")
        if not isinstance(description, str) or not description.strip():
            raise ManifestError("description is required")

        install = data.get("install") or {}
        if not isinstance(install, dict):
            raise ManifestError("install must be an object")
        lifecycle: dict[str, list[str]] = {}
        for field_name in ("setup", "update", "remove"):
            raw_value = install.get(field_name) or []
            if isinstance(raw_value, dict) and not all(
                isinstance(value, list) and all(isinstance(item, str) for item in value)
                for value in raw_value.values()
            ):
                raise ManifestError(
                    f"install.{field_name} platform values must be lists of shell commands"
                )
            value = platform_value(raw_value, f"install.{field_name}") or []
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ManifestError(f"install.{field_name} must be a list of shell commands")
            lifecycle[field_name] = value
        raw_commands = data.get("commands") or {}
        raw_command = data.get("command")
        if isinstance(raw_command, dict) and not all(
            isinstance(value, str) and value.strip() for value in raw_command.values()
        ):
            raise ManifestError("command platform values must be non-empty shell commands")
        command = platform_value(raw_command, "command")
        tags = data.get("tags") or []
        platforms = install.get("platforms") or []
        if not isinstance(raw_commands, dict):
            raise ManifestError("commands must map launcher names to shell commands")
        commands: dict[str, str] = {}
        for launcher_name, raw_value in raw_commands.items():
            if not isinstance(launcher_name, str) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._-]*", launcher_name
            ):
                raise ManifestError(
                    "command names must contain only letters, numbers, '.', '_' and '-'"
                )
            if isinstance(raw_value, dict) and not all(
                isinstance(value, str) and value.strip() for value in raw_value.values()
            ):
                raise ManifestError("commands platform values must be non-empty shell commands")
            value = platform_value(raw_value, f"commands.{launcher_name}")
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ManifestError("commands must map launcher names to shell commands")
            if value:
                commands[launcher_name] = value.strip()
        if command is not None and (not isinstance(command, str) or not command.strip()):
            raise ManifestError("command must be a non-empty shell command or platform mapping")
        for label, values in (("tags", tags), ("install.platforms", platforms)):
            if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
                raise ManifestError(f"{label} must be a list of strings")

        return cls(
            schema=1,
            name=name,
            description=description.strip(),
            repo=repo,
            tags=tuple(tags),
            platforms=tuple(platforms),
            setup=tuple(lifecycle["setup"]),
            update=tuple(lifecycle["update"]),
            remove=tuple(lifecycle["remove"]),
            commands=commands,
            command=command.strip() if command else None,
            homepage=data.get("homepage"),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema": self.schema,
            "name": self.name,
            "description": self.description,
            "repo": self.repo,
            "tags": list(self.tags),
            "install": {
                "platforms": list(self.platforms),
                "setup": list(self.setup),
                "update": list(self.update),
                "remove": list(self.remove),
            },
            "commands": self.commands,
        }
        if self.command:
            result["command"] = self.command
        if self.homepage:
            result["homepage"] = self.homepage
        return result

    def entry_commands(self) -> dict[str, str]:
        """Return every launcher name and its checkout-local entry command."""
        result = {name: command for name, command in self.commands.items() if name != "default"}
        if self.command:
            result.setdefault(self.name, self.command)
        elif default_command := self.commands.get("default"):
            result.setdefault(self.name, default_command)
        return result

    def command_for(self, launcher_name: str) -> str | None:
        for name, command in self.entry_commands().items():
            if name.casefold() == launcher_name.casefold():
                return command
        return None
