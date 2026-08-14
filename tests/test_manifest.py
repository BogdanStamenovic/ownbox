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
commands:
  run: python -m demo
""",
        "octocat/demo-tool",
    )
    assert manifest.name == "demo-tool"
    assert manifest.repo == "octocat/demo-tool"
    assert manifest.setup == ("pip install -e .",)


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
