import pytest

from ownbox.settings import (
    DEFAULT_KEEP_HISTORY,
    all_settings,
    get_setting,
    keep_history,
    load_config,
    save_config,
    set_setting,
)


def test_load_config_returns_empty_dict_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("ownbox.settings.current_platform", lambda: "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert load_config() == {}


def test_load_config_rejects_malformed_yaml(tmp_path, monkeypatch):
    monkeypatch.setattr("ownbox.settings.current_platform", lambda: "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = tmp_path / "ownbox" / "config.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("owner: [unterminated")

    with pytest.raises(RuntimeError, match="config.yaml"):
        load_config()


def test_load_config_rejects_non_mapping(tmp_path, monkeypatch):
    monkeypatch.setattr("ownbox.settings.current_platform", lambda: "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = tmp_path / "ownbox" / "config.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("- just\n- a\n- list\n")

    with pytest.raises(RuntimeError, match="config.yaml"):
        load_config()


def test_save_config_preserves_existing_owner_key(tmp_path, monkeypatch):
    """Regression: save_config must merge, not overwrite (cli.py's save_owner writes
    'owner' to the same file; a settings write must not destroy it)."""
    monkeypatch.setattr("ownbox.settings.current_platform", lambda: "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    save_config({"owner": "someone"})

    save_config({"keep-history": 3})

    assert load_config() == {"owner": "someone", "keep-history": 3}


def test_settings_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr("ownbox.settings.current_platform", lambda: "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert get_setting("keep-history") == DEFAULT_KEEP_HISTORY
    assert set_setting("keep-history", "9") == 9
    assert get_setting("keep-history") == 9
    assert keep_history() == 9
    assert all_settings() == {"keep-history": 9}


def test_get_setting_unknown_key_names_valid_keys(tmp_path, monkeypatch):
    monkeypatch.setattr("ownbox.settings.current_platform", lambda: "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    with pytest.raises(RuntimeError, match="keep-history"):
        get_setting("nope")


def test_set_setting_unknown_key_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr("ownbox.settings.current_platform", lambda: "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    with pytest.raises(RuntimeError, match="unknown setting"):
        set_setting("nope", "1")


@pytest.mark.parametrize("raw", ["-1", "not-a-number", "1.5", ""])
def test_set_setting_rejects_invalid_keep_history(tmp_path, monkeypatch, raw):
    monkeypatch.setattr("ownbox.settings.current_platform", lambda: "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    with pytest.raises(RuntimeError, match="keep-history"):
        set_setting("keep-history", raw)

    # A rejected value must not have been persisted.
    assert get_setting("keep-history") == DEFAULT_KEEP_HISTORY


def test_keep_history_zero_is_valid(tmp_path, monkeypatch):
    monkeypatch.setattr("ownbox.settings.current_platform", lambda: "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert set_setting("keep-history", "0") == 0
    assert keep_history() == 0


def test_get_setting_rejects_invalid_hand_edited_value(tmp_path, monkeypatch):
    """config.yaml is user-editable, so a bad stored value must fail loudly on read."""
    monkeypatch.setattr("ownbox.settings.current_platform", lambda: "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = tmp_path / "ownbox" / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("owner: someone\nkeep-history: not-a-number\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="invalid 'keep-history'"):
        keep_history()
