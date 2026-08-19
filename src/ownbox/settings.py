from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .manifest import current_platform

DEFAULT_KEEP_HISTORY = 5


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def config_home() -> Path:
    if current_platform() == "windows":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "ownbox"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "ownbox"


def _config_path() -> Path:
    return config_home() / "config.yaml"


def load_config() -> dict[str, Any]:
    """Read config.yaml, returning {} if it doesn't exist yet."""
    path = _config_path()
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RuntimeError(f"{path} is not valid YAML: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        # RuntimeError (not TypeError) to match the rest of the codebase's convention
        # of RuntimeError for user-facing failures.
        raise RuntimeError(  # noqa: TRY004
            f"{path} must contain a YAML mapping, not {type(data).__name__}"
        )
    return data


def save_config(updates: dict[str, Any]) -> None:
    """Merge `updates` into the existing config.yaml and write it back atomically.

    This is a read-modify-write merge, not an overwrite: other top-level keys
    already in the file (e.g. "owner", written by cli.py's save_owner()) are
    preserved untouched.
    """
    data = load_config()
    data.update(updates)
    _atomic_write(_config_path(), yaml.safe_dump(data, sort_keys=False))


def _parse_keep_history(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise RuntimeError(f"keep-history must be a non-negative integer, got {raw!r}") from None
    if value < 0:
        raise RuntimeError(f"keep-history must be a non-negative integer, got {raw!r}")
    return value


@dataclass(frozen=True)
class SettingSpec:
    parse: Callable[[str], Any]
    default: Any
    help: str


# Adding a new setting is a one-line change: add an entry mapping its key to a
# SettingSpec (parser/validator, default, and a one-line help text).
SETTINGS: dict[str, SettingSpec] = {
    "keep-history": SettingSpec(
        parse=_parse_keep_history,
        default=DEFAULT_KEEP_HISTORY,
        help="Number of prior revisions kept per tool for 'ownbox rollback' (0 disables history).",
    ),
}


def _known_keys() -> str:
    return ", ".join(sorted(SETTINGS))


def get_setting(key: str) -> Any:
    spec = SETTINGS.get(key)
    if spec is None:
        raise RuntimeError(f"unknown setting {key!r}; valid settings: {_known_keys()}")
    data = load_config()
    if key not in data:
        return spec.default
    # config.yaml is hand-editable, so validate on read too: otherwise an invalid
    # stored value reaches callers unchecked (e.g. a non-integer keep-history
    # would blow up where the history list is trimmed).
    try:
        return spec.parse(str(data[key]))
    except RuntimeError as exc:
        raise RuntimeError(f"invalid {key!r} in {_config_path()}: {exc}") from None


def set_setting(key: str, raw: str) -> Any:
    spec = SETTINGS.get(key)
    if spec is None:
        raise RuntimeError(f"unknown setting {key!r}; valid settings: {_known_keys()}")
    value = spec.parse(raw)
    save_config({key: value})
    return value


def all_settings() -> dict[str, Any]:
    return {key: get_setting(key) for key in SETTINGS}


def keep_history() -> int:
    return get_setting("keep-history")
