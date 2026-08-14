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
            ]
        )
        == 0
    )
    text = (tmp_path / "ownbox.yaml").read_text()
    assert "name: demo" in text
    assert "description: A demo" in text
    assert "setup: []" in text
    assert "command: .venv/bin/demo" in text


def test_init_requires_entry_command(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert main(["init", "--name", "demo"]) == 1
    assert not (tmp_path / "ownbox.yaml").exists()


def test_tool_arguments_pass_through_to_entry_command(tmp_path, monkeypatch):
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
