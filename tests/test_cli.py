from pathlib import Path

from ownbox.cli import dispatch_tool, main
from ownbox.settings import SettingSpec


def test_init_creates_manifest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert (
        main(
            [
                "init",
                "--name",
                "demo",
                "--description",
                "A demo",
                "--command",
                ".venv/bin/demo",
                "--update",
                ".venv/bin/python -m pip install -e .",
                "--remove",
                ".venv/bin/python -m demo.cleanup",
            ]
        )
        == 0
    )
    text = (tmp_path / "ownbox.yaml").read_text()
    assert "name: demo" in text
    assert "description: A demo" in text
    assert "setup: []" in text
    assert "update:\n  - .venv/bin/python -m pip install -e ." in text
    assert "remove:\n  - .venv/bin/python -m demo.cleanup" in text
    assert "command: .venv/bin/demo" in text


def test_init_requires_entry_command(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert main(["init", "--name", "demo"]) == 1
    assert not (tmp_path / "ownbox.yaml").exists()


def test_init_uses_current_platform(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("ownbox.cli.current_platform", lambda: "windows")

    assert main(["init", "--name", "demo", "--command", "demo.exe"]) == 0
    assert "platforms:\n  - windows" in (tmp_path / "ownbox.yaml").read_text()


def test_tool_arguments_pass_through_to_entry_command(tmp_path, monkeypatch):
    caller = tmp_path / "caller"
    caller.mkdir()
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.chdir(caller)
    monkeypatch.setattr("ownbox.cli.current_platform", lambda: "linux")
    (checkout / "ownbox.yaml").write_text(
        "schema: 1\nname: demo\ndescription: Demo\ncommand: bin/demo\n"
    )
    monkeypatch.setattr(
        "ownbox.cli.installations",
        lambda: {"demo": {"path": str(checkout), "repo": "me/demo"}},
    )
    calls = []

    class Result:
        returncode = 0

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return Result()

    monkeypatch.setattr("ownbox.cli.subprocess.run", fake_run)
    assert dispatch_tool("demo", ["render", "two words", "--fast"]) == 0
    assert calls[0][0] == f"{checkout}/bin/demo render 'two words' --fast"
    assert calls[0][1]["cwd"] == caller
    assert calls[0][1]["env"]["OWNBOX_TOOL_DIR"] == str(checkout)


def test_path_entry_command_runs_unchanged_from_callers_directory(tmp_path, monkeypatch):
    caller = tmp_path / "caller"
    caller.mkdir()
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.chdir(caller)
    monkeypatch.setattr("ownbox.cli.current_platform", lambda: "linux")
    (checkout / "ownbox.yaml").write_text(
        "schema: 1\nname: demo\ndescription: Demo\ncommand: python -m demo\n"
    )
    monkeypatch.setattr(
        "ownbox.cli.installations",
        lambda: {"demo": {"path": str(checkout), "repo": "me/demo"}},
    )
    calls = []

    class Result:
        returncode = 0

    monkeypatch.setattr(
        "ownbox.cli.subprocess.run",
        lambda command, **kwargs: calls.append((command, kwargs)) or Result(),
    )

    assert dispatch_tool("demo", []) == 0
    assert calls[0][0] == "python -m demo"
    assert calls[0][1]["cwd"] == caller


def test_named_launcher_uses_its_own_entry_command(tmp_path, monkeypatch):
    monkeypatch.setattr("ownbox.cli.current_platform", lambda: "linux")
    (tmp_path / "ownbox.yaml").write_text(
        "schema: 1\nname: demo\ndescription: Demo\n"
        "commands:\n  demo: bin/demo\n  helper: bin/helper\n"
    )
    monkeypatch.setattr(
        "ownbox.cli.installations",
        lambda: {
            "demo": {
                "path": str(tmp_path),
                "repo": "me/demo",
                "launchers": {"demo": "/bin/demo", "helper": "/bin/helper"},
            }
        },
    )
    calls = []

    class Result:
        returncode = 0

    monkeypatch.setattr(
        "ownbox.cli.subprocess.run",
        lambda command, **kwargs: calls.append((command, kwargs)) or Result(),
    )

    assert dispatch_tool("helper", ["two words"]) == 0
    assert calls[0][0] == f"{tmp_path}/bin/helper 'two words'"


def test_windows_tool_arguments_use_windows_quoting(tmp_path, monkeypatch):
    (tmp_path / "ownbox.yaml").write_text(
        "schema: 1\nname: demo\ndescription: Demo\ncommand: bin\\demo.exe\n"
    )
    monkeypatch.setattr("ownbox.cli.current_platform", lambda: "windows")
    monkeypatch.setattr(
        "ownbox.cli.installations",
        lambda: {"demo": {"path": str(tmp_path), "repo": "me/demo"}},
    )
    calls = []

    class Result:
        returncode = 0

    monkeypatch.setattr(
        "ownbox.cli.subprocess.run",
        lambda command, **kwargs: calls.append((command, kwargs)) or Result(),
    )

    assert dispatch_tool("demo", ["render", "two words", "--fast"]) == 0
    assert calls[0][0] == f'{tmp_path}/bin\\demo.exe render "two words" --fast'


def test_uninstall_command_keeps_files_when_requested(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        "ownbox.cli.uninstall",
        lambda name, keep_files=False, approve_commands=None: (
            calls.append((name, keep_files)) or tmp_path
        ),
    )

    assert main(["uninstall", "demo", "--keep-files"]) == 0
    assert calls == [("demo", True)]
    assert f"kept checkout at {tmp_path}" in capsys.readouterr().out


def test_installed_tool_can_uninstall_itself(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "ownbox.cli.installations",
        lambda: {"demo": {"path": str(tmp_path), "repo": "me/demo"}},
    )
    monkeypatch.setattr("ownbox.cli.uninstall", lambda name, approve_commands=None: tmp_path)

    assert dispatch_tool("demo", ["uninstall"]) == 0
    assert "Uninstalled demo" in capsys.readouterr().out


def test_installed_tool_remove_is_native_uninstall_alias(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "ownbox.cli.installations",
        lambda: {"demo": {"path": str(tmp_path), "repo": "me/demo"}},
    )
    calls = []
    monkeypatch.setattr(
        "ownbox.cli.uninstall",
        lambda name, approve_commands=None: calls.append((name, approve_commands)) or tmp_path,
    )

    assert dispatch_tool("demo", ["remove", "--yes"]) == 0
    assert calls[0][0] == "demo"
    assert calls[0][1](("cleanup",)) is True
    assert "Uninstalled demo" in capsys.readouterr().out


def test_update_all_happy_path(monkeypatch, capsys):
    monkeypatch.setattr(
        "ownbox.cli.installations",
        lambda: {
            "b": {"path": "/p/b", "state": "complete"},
            "a": {"path": "/p/a", "state": "complete"},
        },
    )
    calls = []

    def fake_update(name, approve_commands=None):
        calls.append(name)
        return Path(f"/p/{name}")

    monkeypatch.setattr("ownbox.cli.update", fake_update)

    assert main(["update-all", "--yes"]) == 0
    assert calls == ["a", "b"]
    out = capsys.readouterr().out
    assert "a: updated at /p/a" in out
    assert "b: updated at /p/b" in out
    assert "update-all: 2 updated, 0 skipped, 0 failed" in out


def test_update_all_continues_past_failing_tool(monkeypatch, capsys):
    monkeypatch.setattr(
        "ownbox.cli.installations",
        lambda: {"a": {"path": "/p/a"}, "b": {"path": "/p/b"}},
    )

    def fake_update(name, approve_commands=None):
        if name == "a":
            raise RuntimeError("boom")
        return Path("/p/b")

    monkeypatch.setattr("ownbox.cli.update", fake_update)

    assert main(["update-all", "--yes"]) == 1
    out = capsys.readouterr().out
    assert "a: failed (boom)" in out
    assert "b: updated at /p/b" in out
    assert "update-all: 1 updated, 0 skipped, 1 failed" in out


def test_update_all_skips_incomplete_installs(monkeypatch, capsys):
    monkeypatch.setattr(
        "ownbox.cli.installations",
        lambda: {
            "a": {"path": "/p/a", "state": "incomplete"},
            "b": {"path": "/p/b"},
        },
    )
    calls = []
    monkeypatch.setattr(
        "ownbox.cli.update",
        lambda name, approve_commands=None: calls.append(name) or Path("/p/b"),
    )

    assert main(["update-all", "--yes"]) == 0
    assert calls == ["b"]
    out = capsys.readouterr().out
    assert "a: skipped (incomplete installation)" in out
    assert "update-all: 1 updated, 1 skipped, 0 failed" in out


def test_update_all_nothing_installed(monkeypatch, capsys):
    monkeypatch.setattr("ownbox.cli.installations", dict)

    assert main(["update-all"]) == 0
    assert "No tools installed yet." in capsys.readouterr().out


def test_rollback_command_passes_steps_and_force(monkeypatch, capsys):
    calls = []

    def fake_rollback(name, steps, approve_commands=None, force=False):
        calls.append((name, steps, force))
        assert approve_commands(("cmd",)) is True
        return Path("/p/demo"), "abcdef1234567890"

    monkeypatch.setattr("ownbox.cli.rollback", fake_rollback)

    assert main(["rollback", "demo", "2", "--yes", "--force"]) == 0
    assert calls == [("demo", 2, True)]
    assert "Rolled back demo to abcdef1 at /p/demo" in capsys.readouterr().out


def test_rollback_command_defaults_to_one_step(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "ownbox.cli.rollback",
        lambda name, steps, approve_commands=None, force=False: (
            calls.append((name, steps, force)) or (Path("/p/demo"), "abcdef1")
        ),
    )

    assert main(["rollback", "demo"]) == 0
    assert calls == [("demo", 1, False)]


def test_dispatch_tool_rollback_wiring(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "ownbox.cli.installations",
        lambda: {"demo": {"path": str(tmp_path), "repo": "me/demo"}},
    )
    calls = []

    def fake_rollback(name, steps, approve_commands=None, force=False):
        calls.append((name, steps, force))
        return tmp_path, "1234567abcdef"

    monkeypatch.setattr("ownbox.cli.rollback", fake_rollback)

    assert dispatch_tool("demo", ["rollback", "3", "--force", "--yes"]) == 0
    assert calls == [("demo", 3, True)]
    assert f"Rolled back demo to 1234567 at {tmp_path}" in capsys.readouterr().out


def test_dispatch_tool_rollback_bad_args_usage_error(monkeypatch, capsys):
    monkeypatch.setattr(
        "ownbox.cli.installations",
        lambda: {"demo": {"path": "/p/demo", "repo": "me/demo"}},
    )

    assert dispatch_tool("demo", ["rollback", "--bogus"]) == 1
    assert "usage: <app> rollback" in capsys.readouterr().err


def test_dispatch_tool_info_shows_rollback_targets(tmp_path, monkeypatch, capsys):
    (tmp_path / "ownbox.yaml").write_text(
        "schema: 1\nname: demo\ndescription: Demo\ncommand: bin/demo\n"
    )
    monkeypatch.setattr(
        "ownbox.cli.installations",
        lambda: {
            "demo": {
                "path": str(tmp_path),
                "repo": "me/demo",
                "revision": "abcdef1234567890",
                "history": [
                    {"revision": "2e6bf92aaaa", "recorded_at": "x"},
                    {"revision": "af67c6ebbbb", "recorded_at": "y"},
                ],
            }
        },
    )

    assert dispatch_tool("demo", ["info"]) == 0
    assert "Rollback targets: 2 (2e6bf92, af67c6e)" in capsys.readouterr().out


def test_set_command_with_valid_value(monkeypatch, capsys):
    monkeypatch.setattr(
        "ownbox.cli.set_setting", lambda key, value: int(value) if key == "keep-history" else value
    )

    assert main(["set", "keep-history", "7"]) == 0
    assert "Set keep-history = 7" in capsys.readouterr().out


def test_set_command_with_invalid_value(monkeypatch, capsys):
    def fake_set(key, value):
        raise RuntimeError(f"keep-history must be a non-negative integer, got {value!r}")

    monkeypatch.setattr("ownbox.cli.set_setting", fake_set)

    assert main(["set", "keep-history", "nope"]) == 1
    assert "keep-history must be a non-negative integer" in capsys.readouterr().err


def test_settings_command_prints_key_value_and_help(monkeypatch, capsys):
    monkeypatch.setattr("ownbox.cli.all_settings", lambda: {"keep-history": 5})
    monkeypatch.setattr(
        "ownbox.cli.SETTINGS",
        {
            "keep-history": SettingSpec(
                parse=int, default=5, help="Number of prior revisions kept."
            )
        },
    )

    assert main(["settings"]) == 0
    out = capsys.readouterr().out
    assert "keep-history" in out
    assert "5" in out
    assert "Number of prior revisions kept." in out
