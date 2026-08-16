import pytest

from ownbox.manifest import Manifest, ManifestError


def test_parses_manifest():
    manifest = Manifest.from_text(
        """
schema: 1
name: demo-tool
description: Does useful work
tags: [python, cli]
install:
  platforms: [linux]
  setup: [pip install -e .]
  update: [pip install -e . --upgrade]
  remove: [python -m demo.cleanup]
commands:
  run: python -m demo
""",
        "octocat/demo-tool",
    )
    assert manifest.name == "demo-tool"
    assert manifest.repo == "octocat/demo-tool"
    assert manifest.setup == ("pip install -e .",)
    assert manifest.update == ("pip install -e . --upgrade",)
    assert manifest.remove == ("python -m demo.cleanup",)


@pytest.mark.parametrize(
    "text, message",
    [
        ("[]", "YAML object"),
        ("name: bad/name\ndescription: nope", "name must"),
        ("name: okay", "description is required"),
        ("schema: 2\nname: okay\ndescription: no", "unsupported schema"),
    ],
)
def test_rejects_invalid_manifest(text, message):
    with pytest.raises(ManifestError, match=message):
        Manifest.from_text(text)


def test_round_trip_keeps_repository():
    original = Manifest(
        name="demo", description="Demo", repo="me/demo", tags=("cli",), command="bin/demo"
    )
    restored = Manifest.from_dict(original.to_dict(), original.repo)
    assert restored == original


@pytest.mark.parametrize(
    ("system", "expected_setup", "expected_update", "expected_remove", "expected_command"),
    [
        (
            "Linux",
            (".venv/bin/python -m pip install -e .",),
            (".venv/bin/python -m pip install -U .",),
            (".venv/bin/python -m demo.cleanup",),
            ".venv/bin/demo",
        ),
        (
            "Darwin",
            (".venv/bin/python -m pip install -e .",),
            (".venv/bin/python -m pip install -U .",),
            (".venv/bin/python -m demo.cleanup",),
            ".venv/bin/demo",
        ),
        (
            "Windows",
            (r".venv\Scripts\python.exe -m pip install -e .",),
            (r".venv\Scripts\python.exe -m pip install -U .",),
            (r".venv\Scripts\python.exe -m demo.cleanup",),
            r".venv\Scripts\demo.exe",
        ),
    ],
)
def test_resolves_platform_specific_lifecycle_and_command(
    system, expected_setup, expected_update, expected_remove, expected_command, monkeypatch
):
    monkeypatch.setattr("ownbox.manifest.platform.system", lambda: system)
    manifest = Manifest.from_text(
        r"""
name: demo
description: Cross-platform demo
install:
  platforms: [linux, darwin, windows]
  setup:
    linux: [.venv/bin/python -m pip install -e .]
    darwin: [.venv/bin/python -m pip install -e .]
    windows: ['.venv\Scripts\python.exe -m pip install -e .']
  update:
    linux: [.venv/bin/python -m pip install -U .]
    darwin: [.venv/bin/python -m pip install -U .]
    windows: ['.venv\Scripts\python.exe -m pip install -U .']
  remove:
    default: [.venv/bin/python -m demo.cleanup]
    windows: ['.venv\Scripts\python.exe -m demo.cleanup']
command:
  linux: .venv/bin/demo
  darwin: .venv/bin/demo
  windows: '.venv\Scripts\demo.exe'
"""
    )
    assert manifest.setup == expected_setup
    assert manifest.update == expected_update
    assert manifest.remove == expected_remove
    assert manifest.command == expected_command


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("install:\n  setup:\n    solaris: []", "unsupported platform keys"),
        ("install:\n  setup:\n    windows: nope", "must be lists"),
        ("install:\n  update:\n    solaris: []", "unsupported platform keys"),
        ("install:\n  remove:\n    windows: nope", "must be lists"),
        ("command:\n  windows: []", "must be non-empty"),
    ],
)
def test_rejects_invalid_platform_mappings(field, message):
    with pytest.raises(ManifestError, match=message):
        Manifest.from_text(f"name: demo\ndescription: Demo\n{field}\n")
