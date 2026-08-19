import base64
import json
import subprocess
import urllib.error

import pytest

from ownbox.github import GitHubClient, GitHubError, github_token
from ownbox.manifest import Manifest, ManifestError


@pytest.fixture(autouse=True)
def clear_github_env(monkeypatch):
    # Never let the suite see the developer's real GitHub credentials.
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    # GitHubClient(token=None) falls back to github_token(), which shells out to
    # `gh auth token`. Block that by default so tests are hermetic even on a
    # machine with a real, authenticated `gh` CLI; tests of github_token() itself
    # override this.
    def no_gh_cli(*args, **kwargs):
        raise FileNotFoundError("gh must not be invoked in tests")

    monkeypatch.setattr("ownbox.github.subprocess.run", no_gh_cli)


class FakeResponse:
    """Stand-in for the object returned by urllib.request.urlopen()."""

    def __init__(self, data):
        self._body = json.dumps(data).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def http_error(code, reason, body=None):
    fp = None
    if body is not None:
        import io

        fp = io.BytesIO(json.dumps(body).encode("utf-8"))
    return urllib.error.HTTPError("https://api.github.com/x", code, reason, {}, fp)


# --- github_token() ---------------------------------------------------------


def test_github_token_uses_gh_token_env_var(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "from-gh-token")

    def fail_run(*args, **kwargs):
        raise AssertionError("must not shell out when GH_TOKEN is set")

    monkeypatch.setattr("ownbox.github.subprocess.run", fail_run)
    assert github_token() == "from-gh-token"


def test_github_token_uses_github_token_env_var(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "from-github-token")

    def fail_run(*args, **kwargs):
        raise AssertionError("must not shell out when GITHUB_TOKEN is set")

    monkeypatch.setattr("ownbox.github.subprocess.run", fail_run)
    assert github_token() == "from-github-token"


def test_github_token_prefers_gh_token_over_github_token(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "preferred")
    monkeypatch.setenv("GITHUB_TOKEN", "fallback")
    assert github_token() == "preferred"


def test_github_token_falls_back_to_gh_cli(monkeypatch):
    def fake_run(command, **kwargs):
        assert command == ["gh", "auth", "token"]
        return subprocess.CompletedProcess(command, 0, stdout="cli-token\n", stderr="")

    monkeypatch.setattr("ownbox.github.subprocess.run", fake_run)
    assert github_token() == "cli-token"


def test_github_token_returns_none_when_gh_cli_not_installed(monkeypatch):
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("no gh")

    monkeypatch.setattr("ownbox.github.subprocess.run", fake_run)
    assert github_token() is None


def test_github_token_returns_none_when_gh_cli_times_out(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="gh", timeout=5)

    monkeypatch.setattr("ownbox.github.subprocess.run", fake_run)
    assert github_token() is None


def test_github_token_returns_none_when_gh_cli_outputs_nothing(monkeypatch):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="not logged in")

    monkeypatch.setattr("ownbox.github.subprocess.run", fake_run)
    assert github_token() is None


# --- GitHubClient._get() -----------------------------------------------------


def test_get_returns_decoded_json_on_success(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["request"] = request
        return FakeResponse({"ok": True})

    monkeypatch.setattr("ownbox.github.urllib.request.urlopen", fake_urlopen)
    client = GitHubClient(token=None)

    assert client._get("/whatever") == {"ok": True}
    assert captured["request"].full_url == "https://api.github.com/whatever"


def test_get_passes_through_absolute_urls(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["request"] = request
        return FakeResponse({"ok": True})

    monkeypatch.setattr("ownbox.github.urllib.request.urlopen", fake_urlopen)
    client = GitHubClient(token=None)

    client._get("https://example.com/foo")
    assert captured["request"].full_url == "https://example.com/foo"


def test_get_sets_authorization_header_when_token_present(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["request"] = request
        return FakeResponse({})

    monkeypatch.setattr("ownbox.github.urllib.request.urlopen", fake_urlopen)
    client = GitHubClient(token="secret-token")

    client._get("/user")
    assert captured["request"].get_header("Authorization") == "Bearer secret-token"


def test_get_omits_authorization_header_when_no_token(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["request"] = request
        return FakeResponse({})

    monkeypatch.setattr("ownbox.github.urllib.request.urlopen", fake_urlopen)
    client = GitHubClient(token=None)

    client._get("/user")
    assert captured["request"].get_header("Authorization") is None


@pytest.mark.parametrize("code", [401, 403, 404])
def test_get_raises_github_error_with_message_from_json_body(monkeypatch, code):
    def fake_urlopen(request, timeout=None):
        raise http_error(code, "reason text", body={"message": "explained by github"})

    monkeypatch.setattr("ownbox.github.urllib.request.urlopen", fake_urlopen)
    client = GitHubClient(token=None)

    with pytest.raises(GitHubError, match=f"GitHub API error {code}: explained by github"):
        client._get("/x")


def test_get_falls_back_to_reason_when_body_is_not_json(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise http_error(403, "rate limit reason", body=None)

    monkeypatch.setattr("ownbox.github.urllib.request.urlopen", fake_urlopen)
    client = GitHubClient(token=None)

    with pytest.raises(GitHubError, match="GitHub API error 403: rate limit reason"):
        client._get("/x")


def test_get_raises_github_error_on_url_error(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.URLError("name resolution failed")

    monkeypatch.setattr("ownbox.github.urllib.request.urlopen", fake_urlopen)
    client = GitHubClient(token=None)

    with pytest.raises(GitHubError, match="could not reach GitHub: name resolution failed"):
        client._get("/x")


# --- current_user() ----------------------------------------------------------


def test_current_user_raises_without_token():
    client = GitHubClient(token=None)
    with pytest.raises(GitHubError, match="no GitHub login found"):
        client.current_user()


def test_current_user_returns_login(monkeypatch):
    client = GitHubClient(token="tok")
    monkeypatch.setattr(client, "_get", lambda path: {"login": "octocat"})
    assert client.current_user() == "octocat"


# --- repositories() -----------------------------------------------------------


def test_repositories_uses_authenticated_endpoint_for_own_repos(monkeypatch):
    client = GitHubClient(token="tok")
    monkeypatch.setattr(client, "current_user", lambda: "Octocat")
    seen_paths = []

    def fake_get(path):
        seen_paths.append(path)
        return []

    monkeypatch.setattr(client, "_get", fake_get)
    client.repositories("octocat")
    assert seen_paths == ["/user/repos?affiliation=owner&per_page=100&sort=updated&page=1"]


def test_repositories_uses_public_endpoint_for_other_owners(monkeypatch):
    client = GitHubClient(token="tok")
    monkeypatch.setattr(client, "current_user", lambda: "me")
    seen_paths = []

    def fake_get(path):
        seen_paths.append(path)
        return []

    monkeypatch.setattr(client, "_get", fake_get)
    client.repositories("someone-else")
    assert seen_paths == ["/users/someone-else/repos?per_page=100&sort=updated&page=1"]


def test_repositories_uses_public_endpoint_without_token():
    client = GitHubClient(token=None)
    seen_paths = []

    def fake_get(path):
        seen_paths.append(path)
        return []

    client._get = fake_get
    client.repositories("octocat")
    assert seen_paths == ["/users/octocat/repos?per_page=100&sort=updated&page=1"]


def test_repositories_returns_empty_list_when_owner_has_none():
    client = GitHubClient(token=None)
    client._get = lambda path: []
    assert client.repositories("nobody") == []


def test_repositories_paginates_until_a_short_page(monkeypatch):
    client = GitHubClient(token=None)
    page_one = [{"name": f"repo{i}", "full_name": f"o/repo{i}", "archived": False} for i in range(100)]
    page_two = [{"name": "last", "full_name": "o/last", "archived": False}]
    calls = []

    def fake_get(path):
        calls.append(path)
        if path.endswith("page=1"):
            return page_one
        if path.endswith("page=2"):
            return page_two
        raise AssertionError(f"unexpected page in {path}")

    client._get = fake_get
    repos = client.repositories("o")
    assert [repo["name"] for repo in repos] == [f"repo{i}" for i in range(100)] + ["last"]
    assert calls == [
        "/users/o/repos?per_page=100&sort=updated&page=1",
        "/users/o/repos?per_page=100&sort=updated&page=2",
    ]


def test_repositories_filters_out_archived_repos():
    client = GitHubClient(token=None)
    client._get = lambda path: [
        {"name": "alive", "full_name": "o/alive", "archived": False},
        {"name": "dead", "full_name": "o/dead", "archived": True},
    ]
    repos = client.repositories("o")
    assert [repo["name"] for repo in repos] == ["alive"]


def test_repositories_raises_on_unexpected_response_shape():
    client = GitHubClient(token=None)
    client._get = lambda path: {"not": "a list"}
    with pytest.raises(GitHubError, match="unexpected repository response"):
        client.repositories("o")


# --- manifest() ----------------------------------------------------------------


def test_manifest_returns_parsed_manifest_for_valid_yaml():
    client = GitHubClient(token=None)
    text = "name: demo\ndescription: Demo tool\n"
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    client._get = lambda path: {"content": encoded}

    manifest = client.manifest("octocat/demo")
    assert manifest is not None
    assert manifest.name == "demo"
    assert manifest.repo == "octocat/demo"


def test_manifest_returns_none_when_repo_has_no_manifest():
    client = GitHubClient(token=None)

    def fake_get(path):
        raise GitHubError("GitHub API error 404: Not Found")

    client._get = fake_get
    assert client.manifest("octocat/no-manifest") is None


def test_manifest_reraises_non_404_github_errors():
    client = GitHubClient(token=None)

    def fake_get(path):
        raise GitHubError("GitHub API error 500: Internal Server Error")

    client._get = fake_get
    with pytest.raises(GitHubError, match="500"):
        client.manifest("octocat/broken")


def test_manifest_returns_none_when_response_has_no_content_key():
    client = GitHubClient(token=None)
    client._get = lambda path: {"type": "dir"}
    assert client.manifest("octocat/weird") is None


def test_manifest_raises_manifest_error_for_malformed_yaml():
    client = GitHubClient(token=None)
    # Missing required "description" field: Manifest.from_dict() rejects it.
    text = "name: demo\n"
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    client._get = lambda path: {"content": encoded}

    with pytest.raises(ManifestError, match="description is required"):
        client.manifest("octocat/malformed")


# --- discover() ------------------------------------------------------------------


def test_discover_returns_manifests_and_warnings_for_mixed_repos():
    client = GitHubClient(token=None)
    repos = [
        {
            "name": "has-manifest",
            "full_name": "o/has-manifest",
            "description": None,
            "topics": [],
            "language": None,
            "html_url": "https://github.com/o/has-manifest",
        },
        {
            "name": "no-manifest",
            "full_name": "o/no-manifest",
            "description": "A tool without ownbox.yaml",
            "topics": ["cli"],
            "language": "Python",
            "html_url": "https://github.com/o/no-manifest",
        },
        {
            "name": "broken",
            "full_name": "o/broken",
            "description": None,
            "topics": [],
            "language": None,
            "html_url": "https://github.com/o/broken",
        },
    ]
    client.repositories = lambda owner: repos

    def fake_manifest(full_name):
        if full_name == "o/has-manifest":
            return Manifest(name="has-manifest", description="Has one", repo=full_name)
        if full_name == "o/no-manifest":
            return None
        raise GitHubError("GitHub API error 500: boom")

    client.manifest = fake_manifest

    manifests, warnings = client.discover("o")

    assert [m.name for m in manifests] == ["has-manifest", "no-manifest"]
    assert warnings == ["o/broken: GitHub API error 500: boom"]

    synthesized = next(m for m in manifests if m.name == "no-manifest")
    assert synthesized.description == "A tool without ownbox.yaml"
    assert synthesized.tags == ("cli", "python")
    assert synthesized.homepage == "https://github.com/o/no-manifest"
    assert synthesized.repo == "o/no-manifest"


def test_discover_sorts_manifests_by_name_casefold():
    client = GitHubClient(token=None)
    repos = [
        {"name": "Zebra", "full_name": "o/Zebra", "topics": [], "language": None},
        {"name": "apple", "full_name": "o/apple", "topics": [], "language": None},
        {"name": "Mango", "full_name": "o/Mango", "topics": [], "language": None},
    ]
    client.repositories = lambda owner: repos
    client.manifest = lambda full_name: None

    manifests, warnings = client.discover("o")

    assert [m.name for m in manifests] == ["apple", "Mango", "Zebra"]
    assert warnings == []


def test_discover_returns_empty_results_when_owner_has_no_repos():
    client = GitHubClient(token=None)
    client.repositories = lambda owner: []
    manifests, warnings = client.discover("o")
    assert manifests == []
    assert warnings == []


def test_discover_uses_default_description_when_repo_has_none():
    client = GitHubClient(token=None)
    repos = [{"name": "bare", "full_name": "o/bare", "topics": [], "language": None}]
    client.repositories = lambda owner: repos
    client.manifest = lambda full_name: None

    manifests, _warnings = client.discover("o")

    assert manifests[0].description == "GitHub repository o/bare"
