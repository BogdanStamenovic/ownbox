from __future__ import annotations

import errno
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import IO

from .manifest import Manifest, current_platform
from .settings import _atomic_write, config_home, keep_history

# Re-exported for backward compatibility: cli.py and tests import config_home
# and _atomic_write from ownbox.store, but the implementations now live in
# settings.py (which store.py depends on for keep_history()) to avoid a
# store <-> settings import cycle.
__all__ = ["_atomic_write", "config_home"]

# Network-bound git plumbing (clone/fetch/merge/rev-parse/show) gets its own budget,
# separate from arbitrary tool-authored setup/update/remove shell commands, which may
# legitimately run longer (e.g. compiling something).
CLONE_TIMEOUT = int(os.environ.get("OWNBOX_CLONE_TIMEOUT", "600"))
COMMAND_TIMEOUT = int(os.environ.get("OWNBOX_COMMAND_TIMEOUT", "1800"))


def _run(command, *, timeout: int, check: bool = False, **kwargs):
    try:
        return subprocess.run(command, timeout=timeout, check=check, **kwargs)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"command timed out after {timeout}s: {command}") from exc


def data_home() -> Path:
    if current_platform() == "windows":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "ownbox"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "ownbox"


def cache_home() -> Path:
    if current_platform() == "windows":
        return data_home() / "cache"
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "ownbox"


def bin_home() -> Path:
    if os.environ.get("OWNBOX_BIN_DIR"):
        return Path(os.environ["OWNBOX_BIN_DIR"])
    if current_platform() == "windows":
        return data_home() / "bin"
    return Path.home() / ".local/bin"


def claude_skills_home() -> Path:
    """Where Claude Code discovers agent skills: one directory per skill.

    Overridable with OWNBOX_SKILLS_DIR, mirroring how OWNBOX_BIN_DIR overrides the
    launcher directory. Same location on every platform because Claude Code reads
    ~/.claude/skills regardless of OS.
    """
    if os.environ.get("OWNBOX_SKILLS_DIR"):
        return Path(os.environ["OWNBOX_SKILLS_DIR"])
    return Path.home() / ".claude" / "skills"


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
        payload = {
            "owner": self.owner,
            "synced_at": self.synced_at,
            "tools": [tool.to_dict() for tool in self.tools],
        }
        _atomic_write(path, json.dumps(payload, indent=2) + "\n")

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
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"installed.json is corrupt or truncated: {path}") from exc


def save_installations(state: dict[str, dict]) -> None:
    path = data_home() / "installed.json"
    _atomic_write(path, json.dumps(state, indent=2) + "\n")


@contextmanager
def state_lock() -> Iterator[None]:
    """Exclusive lock on installed.json, held only around a read-modify-write.

    Several agents run ownbox on one machine. Without this, an install or update that loaded
    the state before a long lifecycle run wrote the whole file back afterwards and silently
    reverted every other tool's entry changed in between (lost update, seen 2026-11-10).
    A sidecar file is locked because installed.json itself is replaced atomically, so a lock
    on it would stay on the replaced inode. POSIX uses flock; Windows uses msvcrt.locking on
    byte 0 of the sidecar.
    """
    path = data_home() / "installed.json.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+b") as handle:
        _lock_file(handle)
        try:
            yield
        finally:
            _unlock_file(handle)


def _lock_file(handle: IO[bytes]) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        while True:
            try:
                # LK_LOCK retries for about 10 s and then raises; keep waiting, as flock does.
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                return
            except OSError as exc:
                if exc.errno != errno.EDEADLOCK:  # anything but "still locked": fail loudly
                    raise
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock_file(handle: IO[bytes]) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def commit_installation(name: str, entry: dict | None) -> None:
    """Write one tool's entry (or delete it with None) into the current installed.json.

    Re-reads the file under the lock so entries other processes changed since this one
    loaded its copy survive; only `name` is replaced.
    """
    with state_lock():
        state = installations()
        if entry is None:
            state.pop(name, None)
        else:
            state[name] = entry
        save_installations(state)


def launcher_path(name: str) -> Path:
    suffix = ".cmd" if current_platform() == "windows" else ""
    return bin_home() / f"{name}{suffix}"


def check_launcher(name: str) -> Path:
    path = launcher_path(name)
    if (
        path.exists()
        and "generated by ownbox"
        not in path.read_text(encoding="utf-8", errors="ignore").casefold()
    ):
        raise RuntimeError(f"refusing to replace existing command: {path}")
    return path


def create_launcher(name: str) -> Path:
    path = launcher_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    if current_platform() == "windows":
        path.write_text(
            f'@echo off\nrem generated by ownbox\nownbox "{name}" %*\nexit /b %errorlevel%\n',
            encoding="utf-8",
        )
    else:
        path.write_text(
            f'#!/bin/sh\n# generated by ownbox\nexec ownbox {name!r} "$@"\n',
            encoding="utf-8",
        )
        path.chmod(0o755)
    return path


def launcher_names(tool: Manifest) -> tuple[str, ...]:
    names = tuple(tool.entry_commands())
    if names:
        return names
    # A skill-only tool ships instructions, not an executable, so it gets no
    # launcher; the tool.name fallback exists only for a runnable tool that
    # somehow declared no explicit command.
    if tool.skills:
        return ()
    return (tool.name,)


def create_launchers(tool: Manifest) -> dict[str, str]:
    return {name: str(create_launcher(name)) for name in launcher_names(tool)}


def skill_link_name(rel_path: str) -> str:
    """The directory name a skill is installed under in the skills home.

    A skill is a directory holding SKILL.md; if the manifest points straight at a
    SKILL.md file the parent directory names it. Claude Code identifies a skill by
    this directory name, so it must match the skill's own `name:` frontmatter.
    """
    path = Path(rel_path)
    if path.name.casefold() == "skill.md":
        path = path.parent
    return path.name


def skill_dest_paths(tool: Manifest) -> dict[str, Path]:
    """Map each declared skill to where it will be installed, without touching disk."""
    home = claude_skills_home()
    return {skill_link_name(rel): home / skill_link_name(rel) for rel in tool.skills}


def _skill_source(target: Path, rel_path: str) -> Path:
    """Resolve a skill's source directory inside the checkout, refusing to escape it."""
    path = Path(rel_path)
    if path.name.casefold() == "skill.md":
        path = path.parent
    source = (target / path).resolve()
    checkout = target.resolve()
    if checkout != source and checkout not in source.parents:
        raise RuntimeError(f"skill path escapes the checkout: {rel_path}")
    if not source.is_dir():
        raise RuntimeError(f"skill directory not found in checkout: {rel_path}")
    if not (source / "SKILL.md").is_file():
        raise RuntimeError(f"skill directory has no SKILL.md: {rel_path}")
    return source


def _owns_skill(dest: Path, target: Path) -> bool:
    """True if `dest` is a skill Ownbox installed from `target` and is safe to remove."""
    if dest.is_symlink():
        try:
            return target.resolve() in dest.resolve().parents or dest.resolve().parent == target.resolve()
        except OSError:
            return False
    # A copied skill (Windows, or a symlink-less filesystem) carries a marker.
    return (dest / ".ownbox-skill").is_file()


def check_skill_dest(name: str, target: Path) -> Path:
    dest = claude_skills_home() / name
    if dest.exists() and not _owns_skill(dest, target):
        raise RuntimeError(f"refusing to replace existing skill not installed by ownbox: {dest}")
    return dest


def install_skills(tool: Manifest, target: Path) -> dict[str, str]:
    """Link (or copy) each declared skill into the Claude Code skills directory.

    On POSIX a symlink into the checkout is created, so `ownbox update` refreshes
    the skill content for free. Where symlinks are unavailable (Windows without the
    privilege) the directory is copied and stamped with a marker so uninstall can
    tell it apart from a hand-made skill of the same name.
    """
    installed: dict[str, str] = {}
    home = claude_skills_home()
    home.mkdir(parents=True, exist_ok=True)
    for rel in tool.skills:
        name = skill_link_name(rel)
        source = _skill_source(target, rel)
        dest = check_skill_dest(name, target)
        if dest.exists() or dest.is_symlink():
            if dest.is_symlink() or dest.is_file():
                dest.unlink()
            else:
                shutil.rmtree(dest)
        try:
            dest.symlink_to(source, target_is_directory=True)
        except (OSError, NotImplementedError):
            shutil.copytree(source, dest)
            (dest / ".ownbox-skill").write_text("installed by ownbox\n", encoding="utf-8")
        installed[name] = str(dest)
    return installed


def remove_skills(skills: object, target: Path) -> None:
    """Remove skills recorded for a tool, refusing to touch anything Ownbox didn't install."""
    if not isinstance(skills, dict):
        return
    for name, recorded in skills.items():
        dest = Path(recorded) if recorded else claude_skills_home() / name
        if not dest.exists() and not dest.is_symlink():
            continue
        if not _owns_skill(dest, target):
            raise RuntimeError(f"refusing to remove skill not installed by ownbox: {dest}")
        if dest.is_symlink() or dest.is_file():
            dest.unlink()
        else:
            shutil.rmtree(dest)


def installed_launcher_paths(installed_name: str, item: dict) -> dict[str, Path]:
    launchers = item.get("launchers")
    if isinstance(launchers, dict):
        return {name: Path(path).expanduser() for name, path in launchers.items()}
    return {installed_name: Path(item.get("launcher", launcher_path(installed_name))).expanduser()}


def resolve_installation(state: dict[str, dict], name: str) -> tuple[str, dict]:
    matches = []
    for installed_name, item in state.items():
        aliases = installed_launcher_paths(installed_name, item)
        if installed_name.casefold() == name.casefold() or any(
            alias.casefold() == name.casefold() for alias in aliases
        ):
            matches.append((installed_name, item))
    if not matches:
        raise RuntimeError(f"{name!r} is not installed")
    if len(matches) > 1:
        raise RuntimeError(f"command {name!r} belongs to multiple installed tools")
    return matches[0]


def git_revision(target: Path) -> str | None:
    try:
        result = _run(
            ["git", "-C", str(target), "rev-parse", "HEAD"],
            timeout=CLONE_TIMEOUT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return None
    revision = result.stdout.strip()
    return revision or None


def install(
    tool: Manifest,
    destination: Path | None = None,
    approve_commands: Callable[[tuple[str, ...]], bool] | None = None,
) -> Path:
    platform_name = current_platform()
    if tool.platforms and platform_name not in [item.casefold() for item in tool.platforms]:
        raise RuntimeError(f"{tool.name} does not support {platform_name}")
    state = installations()
    occupied = {
        alias.casefold()
        for installed_name, item in state.items()
        for alias in installed_launcher_paths(installed_name, item)
    }
    for name in launcher_names(tool):
        if name.casefold() in occupied:
            raise RuntimeError(f"command is already provided by an installed tool: {name}")
        check_launcher(name)
    target = (destination or data_home() / "tools" / tool.name).expanduser().resolve()
    if target.exists():
        raise RuntimeError(f"destination already exists: {target}")
    # Refuse before cloning if a declared skill would clobber a hand-made one. The
    # destination name is known from the manifest, so this needs no checkout.
    for skill_name in skill_dest_paths(tool):
        check_skill_dest(skill_name, target)
    if tool.setup and approve_commands is not None and not approve_commands(tool.setup):
        raise RuntimeError("setup commands were not approved")
    target.parent.mkdir(parents=True, exist_ok=True)
    clone_url = f"https://github.com/{tool.repo}.git"
    if shutil.which("gh"):
        clone = ["gh", "repo", "clone", tool.repo, str(target)]
    else:
        clone = ["git", "clone", clone_url, str(target)]
    _run(clone, timeout=CLONE_TIMEOUT, check=True)

    # Record the checkout before running setup so a failed setup still leaves a
    # tracked (and therefore uninstallable) entry instead of an orphaned checkout.
    state[tool.name] = {
        "repo": tool.repo,
        "path": str(target),
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "revision": git_revision(target),
        "state": "incomplete",
    }
    commit_installation(tool.name, state[tool.name])

    try:
        for command in tool.setup:
            _run(command, cwd=target, shell=True, check=True, timeout=COMMAND_TIMEOUT)
    except subprocess.CalledProcessError:
        raise RuntimeError(
            f"setup failed; checkout kept at {target} "
            f"(run 'ownbox uninstall {tool.name}' to remove it)"
        ) from None

    launchers = create_launchers(tool)
    state[tool.name]["launchers"] = launchers
    skills = install_skills(tool, target)
    if skills:
        state[tool.name]["skills"] = skills
    state[tool.name]["state"] = "complete"
    commit_installation(tool.name, state[tool.name])
    return target


def uninstall(
    name: str,
    keep_files: bool = False,
    approve_commands: Callable[[tuple[str, ...]], bool] | None = None,
) -> Path:
    state = installations()
    installed_name, item = resolve_installation(state, name)
    target = Path(item["path"]).expanduser()
    launchers = installed_launcher_paths(installed_name, item)

    for launcher in launchers.values():
        if launcher.exists() and (
            not launcher.is_file()
            or "generated by ownbox"
            not in launcher.read_text(encoding="utf-8", errors="ignore").casefold()
        ):
            raise RuntimeError(f"refusing to remove command not generated by Ownbox: {launcher}")

    if not keep_files and target.exists():
        resolved_target = target.resolve()
        if (
            target.is_symlink()
            or resolved_target == Path(resolved_target.anchor)
            or resolved_target == Path.home()
        ):
            raise RuntimeError(f"refusing to remove unsafe checkout path: {target}")

    manifest_path = target / "ownbox.yaml"
    if manifest_path.exists():
        manifest = Manifest.from_path(manifest_path, item["repo"])
        if manifest.remove:
            if approve_commands is not None and not approve_commands(manifest.remove):
                raise RuntimeError("remove commands were not approved")
            for command in manifest.remove:
                _run(command, cwd=target, shell=True, check=True, timeout=COMMAND_TIMEOUT)

    for launcher in launchers.values():
        if launcher.exists():
            launcher.unlink()
    remove_skills(item.get("skills"), target)
    if not keep_files and target.exists():
        shutil.rmtree(target)

    del state[installed_name]
    commit_installation(installed_name, None)
    return target


def _read_manifest_at_ref(target: Path, ref: str, repo: str) -> Manifest | None:
    """Read ownbox.yaml as it exists at `ref`, without touching the working tree.

    Prefers the manifest at `ref` (e.g. "FETCH_HEAD" or a commit sha); falls back to
    whatever manifest is already checked out; falls back to None (no lifecycle
    commands) if neither exists.
    """
    try:
        result = _run(
            ["git", "-C", str(target), "show", f"{ref}:ownbox.yaml"],
            timeout=CLONE_TIMEOUT,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        manifest_path = target / "ownbox.yaml"
        if manifest_path.exists():
            return Manifest.from_path(manifest_path, repo)
        return None
    return Manifest.from_text(result.stdout, repo)


def _read_incoming_manifest(target: Path, repo: str) -> Manifest | None:
    """Read ownbox.yaml as it will look after a fast-forward, without touching the tree."""
    return _read_manifest_at_ref(target, "FETCH_HEAD", repo)


def _refresh_launchers(
    installed_name: str,
    item: dict,
    state: dict[str, dict],
    manifest: Manifest | None,
) -> None:
    """Recreate launchers for `item` from `manifest`, retiring any that are no longer named.

    Shared by update() and rollback(): both land on a new manifest revision and need
    the same "diff old launcher names against new ones" dance.
    """
    if manifest is None:
        create_launcher(installed_name)
        return
    old_launchers = installed_launcher_paths(installed_name, item)
    new_names = launcher_names(manifest)
    occupied = {
        alias.casefold()
        for other_name, other_item in state.items()
        if other_name != installed_name
        for alias in installed_launcher_paths(other_name, other_item)
    }
    for launcher_name in new_names:
        if launcher_name.casefold() in occupied:
            raise RuntimeError(f"command is already provided by an installed tool: {launcher_name}")
        check_launcher(launcher_name)
    retained = {launcher_name.casefold() for launcher_name in new_names}
    for launcher_name, launcher in old_launchers.items():
        if launcher_name.casefold() not in retained and launcher.exists():
            check_launcher(launcher_name)
            launcher.unlink()
    item["launchers"] = create_launchers(manifest)
    item.pop("launcher", None)


def _refresh_skills(item: dict, target: Path, manifest: Manifest | None) -> None:
    """Re-link skills after landing on a new revision, retiring any no longer declared.

    Symlinked skills already track the checkout's content across a fast-forward, so
    the only thing that can change is the set of declared skills — a skill added,
    removed, or renamed in the incoming manifest.
    """
    recorded = item.get("skills")
    old_skills: dict[str, str] = recorded if isinstance(recorded, dict) else {}
    new_names = set(skill_dest_paths(manifest).keys()) if manifest else set()
    stale = {name: path for name, path in old_skills.items() if name not in new_names}
    if stale:
        remove_skills(stale, target)
    if manifest and manifest.skills:
        item["skills"] = install_skills(manifest, target)
    else:
        item.pop("skills", None)


def record_history(item: dict, revision: str | None) -> None:
    """Prepend `revision` onto item["history"], trimmed to the configured keep-history length.

    No-op if `revision` is None. If keep-history is 0, any existing history list is
    dropped instead so it doesn't linger unused.
    """
    keep = keep_history()
    if keep == 0:
        item.pop("history", None)
        return
    if revision is None:
        return
    entry = {"revision": revision, "recorded_at": datetime.now(timezone.utc).isoformat()}
    history = item.get("history") or []
    item["history"] = [entry, *history][:keep]


class UpToDate(Exception):
    """Raised by update() when the fetched commit is the one already installed.

    Nothing is merged and no lifecycle command runs: an unchanged commit must not
    rebuild dependencies or restart services (Bogdan, 2026-11-25).
    """

    def __init__(self, name: str, path: Path, revision: str) -> None:
        super().__init__(f"{name} is already up to date at {revision[:7]}")
        self.name = name
        self.path = path
        self.revision = revision


def _rev_parse(target: Path, ref: str) -> str | None:
    try:
        result = _run(
            ["git", "-C", str(target), "rev-parse", ref],
            timeout=CLONE_TIMEOUT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return None
    return result.stdout.strip() or None


def update(
    name: str,
    approve_commands: Callable[[tuple[str, ...]], bool] | None = None,
    force: bool = False,
) -> Path:
    state = installations()
    installed_name, item = resolve_installation(state, name)
    target = Path(item["path"])
    old_revision = item.get("revision")

    try:
        _run(["git", "-C", str(target), "fetch"], timeout=CLONE_TIMEOUT, check=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"failed to fetch updates for {installed_name}") from exc

    # Skip only when the answer is certain: both revisions known and equal, and the
    # last lifecycle run completed. An incomplete install, or --force, reruns it.
    if not force and item.get("state") != "incomplete":
        fetched = _rev_parse(target, "FETCH_HEAD")
        current = _rev_parse(target, "HEAD")
        if fetched and current and fetched == current:
            raise UpToDate(installed_name, target, current)

    manifest = _read_incoming_manifest(target, item["repo"])
    commands: tuple[str, ...] = ()
    if manifest is not None:
        commands = manifest.update or manifest.setup

    if commands and approve_commands is not None and not approve_commands(commands):
        raise RuntimeError("update commands were not approved; checkout was left unchanged")

    try:
        _run(
            ["git", "-C", str(target), "merge", "--ff-only", "FETCH_HEAD"],
            timeout=CLONE_TIMEOUT,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"failed to fast-forward {installed_name}") from exc

    for command in commands:
        _run(command, cwd=target, shell=True, check=True, timeout=COMMAND_TIMEOUT)

    _refresh_launchers(installed_name, item, state, manifest)
    _refresh_skills(item, target, manifest)
    new_revision = git_revision(target)
    # An up-to-date update is a no-op; recording it would fill the rollback
    # history with duplicates of the current revision and burn every slot.
    if new_revision != old_revision:
        record_history(item, old_revision)
    item["revision"] = new_revision
    item["updated_at"] = datetime.now(timezone.utc).isoformat()
    commit_installation(installed_name, item)
    return target


def rollback(
    name: str,
    steps: int = 1,
    approve_commands: Callable[[tuple[str, ...]], bool] | None = None,
    force: bool = False,
) -> tuple[Path, str]:
    if steps < 1:
        raise RuntimeError(f"steps must be at least 1, got {steps}")

    state = installations()
    installed_name, item = resolve_installation(state, name)
    target = Path(item["path"])

    history = item.get("history") or []
    if not history:
        raise RuntimeError(
            f"no rollback history for {installed_name}; keep-history is {keep_history()}"
        )
    if steps > len(history):
        raise RuntimeError(
            f"only {len(history)} rollback step(s) available for {installed_name}, "
            f"requested {steps}"
        )

    if not force:
        try:
            status = _run(
                # Untracked files are excluded deliberately: 'git reset --hard' leaves
                # them alone, and setup/update commands routinely leave build artifacts
                # behind, which would otherwise make rollback permanently unavailable.
                ["git", "-C", str(target), "status", "--porcelain", "--untracked-files=no"],
                timeout=CLONE_TIMEOUT,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"failed to check working tree status for {installed_name}") from exc
        if status.stdout.strip():
            raise RuntimeError(
                f"{installed_name} has uncommitted changes to tracked files; rollback "
                "would discard them with 'git reset --hard' (use --force to override)"
            )

    target_revision = history[steps - 1]["revision"]
    manifest = _read_manifest_at_ref(target, target_revision, item["repo"])
    commands: tuple[str, ...] = ()
    if manifest is not None:
        commands = manifest.update or manifest.setup

    if commands and approve_commands is not None and not approve_commands(commands):
        raise RuntimeError("rollback commands were not approved; checkout was left unchanged")

    try:
        _run(
            ["git", "-C", str(target), "reset", "--hard", target_revision],
            timeout=CLONE_TIMEOUT,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"failed to reset {installed_name} to {target_revision}") from exc

    for command in commands:
        _run(command, cwd=target, shell=True, check=True, timeout=COMMAND_TIMEOUT)

    _refresh_launchers(installed_name, item, state, manifest)
    _refresh_skills(item, target, manifest)
    item["history"] = history[steps:]
    item["revision"] = target_revision
    item["rolled_back_at"] = datetime.now(timezone.utc).isoformat()
    commit_installation(installed_name, item)
    return target, target_revision
