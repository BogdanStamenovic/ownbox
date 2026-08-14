from ownbox.cli import main


def test_init_creates_manifest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["init", "--name", "demo", "--description", "A demo"]) == 0
    text = (tmp_path / "ownbox.yaml").read_text()
    assert "name: demo" in text
    assert "description: A demo" in text
    assert "setup: []" in text
