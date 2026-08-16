from ownbox.cli import dispatch_tool, main


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
    monkeypatch.setattr("ownbox.cli.current_platform", lambda: "linux")
    (tmp_path / "ownbox.yaml").write_text(
        "schema: 1\nname: demo\ndescription: Demo\ncommand: bin/demo\n"
    )
    monkeypatch.setattr(
        "ownbox.cli.installations",
        lambda: {"demo": {"path": str(tmp_path), "repo": "me/demo"}},
    )
    calls = []

    class Result:
        returncode = 0

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return Result()

    monkeypatch.setattr("ownbox.cli.subprocess.run", fake_run)
    assert dispatch_tool("demo", ["render", "two words", "--fast"]) == 0
    assert calls[0][0] == "bin/demo render 'two words' --fast"
    assert calls[0][1]["cwd"] == tmp_path


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
    assert calls[0][0] == 'bin\\demo.exe render "two words" --fast'


def test_uninstall_command_keeps_files_when_requested(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        "ownbox.cli.uninstall",
        lambda name, keep_files=False, approve_commands=None: calls.append((name, keep_files))
        or tmp_path,
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
