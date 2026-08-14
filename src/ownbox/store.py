from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .manifest import Manifest


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "ownbox"


def cache_home() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "ownbox"


def config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "ownbox"


@dataclass
class Catalog:
    owner: str
    tools: list[Manifest]
    synced_at: str

    @classmethod
    def load(cls) -> Catalog | None:
        path = cache_home() / "catalog.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            owner=data["owner"],
            tools=[Manifest.from_dict(item, item["repo"]) for item in data["tools"]],
            synced_at=data["synced_at"],
        )

    def save(self) -> None:
        path = cache_home() / "catalog.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "owner": self.owner,
            "synced_at": self.synced_at,
            "tools": [tool.to_dict() for tool in self.tools],
        }
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def find(self, query: str) -> list[Manifest]:
        terms = query.casefold().split()

        def score(tool: Manifest) -> tuple[int, str]:
            name = tool.name.casefold()
            haystack = " ".join((tool.name, tool.description, *tool.tags)).casefold()
            points = sum(8 if term == name else 4 if term in name else 1 for term in terms)
            if not all(term in haystack for term in terms):
                points = -1
            return (-points, name)

        return sorted((tool for tool in self.tools if score(tool)[0] < 0), key=score)

    def get(self, name: str) -> Manifest:
        matches = [tool for tool in self.tools if tool.name.casefold() == name.casefold()]
        if not matches:
            raise KeyError(name)
        return matches[0]


def new_catalog(owner: str, tools: list[Manifest]) -> Catalog:
    return Catalog(owner, tools, datetime.now(timezone.utc).isoformat())


def installations() -> dict[str, dict]:
    path = data_home() / "installed.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_installations(state: dict[str, dict]) -> None:
    path = data_home() / "installed.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def install(tool: Manifest, destination: Path | None = None) -> Path:
    current_platform = {"linux": "linux", "darwin": "darwin", "windows": "windows"}.get(
        platform.system().casefold(), platform.system().casefold()
    )
    if tool.platforms and current_platform not in [item.casefold() for item in tool.platforms]:
        raise RuntimeError(f"{tool.name} does not support {current_platform}")
    target = destination or data_home() / "tools" / tool.name
    if target.exists():
        raise RuntimeError(f"destination already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    clone_url = f"https://github.com/{tool.repo}.git"
    if shutil.which("gh"):
        clone = ["gh", "repo", "clone", tool.repo, str(target)]
    else:
        clone = ["git", "clone", clone_url, str(target)]
    subprocess.run(clone, check=True)
    try:
        for command in tool.setup:
            subprocess.run(command, cwd=target, shell=True, check=True)
    except subprocess.CalledProcessError:
        raise RuntimeError(f"setup failed; checkout kept at {target}") from None
    state = installations()
    state[tool.name] = {
        "repo": tool.repo,
        "path": str(target),
        "installed_at": datetime.now(timezone.utc).isoformat(),
    }
    save_installations(state)
    return target


def update(name: str) -> Path:
    state = installations()
    if name not in state:
        raise KeyError(name)
    target = Path(state[name]["path"])
    subprocess.run(["git", "-C", str(target), "pull", "--ff-only"], check=True)
    manifest = Manifest.from_path(target / "ownbox.yaml", state[name]["repo"])
    for command in manifest.setup:
        subprocess.run(command, cwd=target, shell=True, check=True)
    state[name]["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_installations(state)
    return target
