from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class Manifest:
    name: str
    description: str
    repo: str
    tags: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()
    setup: tuple[str, ...] = ()
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
        setup = install.get("setup") or []
        commands = data.get("commands") or {}
        command = data.get("command")
        tags = data.get("tags") or []
        platforms = install.get("platforms") or []
        if not isinstance(setup, list) or not all(isinstance(v, str) for v in setup):
            raise ManifestError("install.setup must be a list of shell commands")
        if not isinstance(commands, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in commands.items()
        ):
            raise ManifestError("commands must map names to shell commands")
        if command is not None and (not isinstance(command, str) or not command.strip()):
            raise ManifestError("command must be a non-empty shell command")
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
            setup=tuple(setup),
            commands=dict(commands),
            command=command.strip() if command else commands.get("default"),
            homepage=data.get("homepage"),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema": self.schema,
            "name": self.name,
            "description": self.description,
            "repo": self.repo,
            "tags": list(self.tags),
            "install": {"platforms": list(self.platforms), "setup": list(self.setup)},
            "commands": self.commands,
        }
        if self.command:
            result["command"] = self.command
        if self.homepage:
            result["homepage"] = self.homepage
        return result
