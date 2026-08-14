from ownbox.manifest import Manifest
from ownbox.store import Catalog


def tool(name, description, tags=()):
    return Manifest(name=name, description=description, repo=f"me/{name}", tags=tags)


def test_catalog_searches_names_descriptions_and_tags():
    catalog = Catalog(
        "me",
        [tool("camera", "Take a photo", ("raspberry-pi",)), tool("notes", "Write things")],
        "now",
    )
    assert [item.name for item in catalog.find("photo")] == ["camera"]
    assert [item.name for item in catalog.find("raspberry")] == ["camera"]
    assert [item.name for item in catalog.find("camera")] == ["camera"]


def test_catalog_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    catalog = Catalog("me", [tool("demo", "Demo")], "now")
    catalog.save()
    loaded = Catalog.load()
    assert loaded is not None
    assert loaded.owner == "me"
    assert loaded.tools[0].name == "demo"
