from __future__ import annotations

import base64
import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from .manifest import Manifest, ManifestError


class GitHubError(RuntimeError):
    pass


def github_token() -> str | None:
    for key in ("GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(key):
            return os.environ[key]
    try:
        result = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=5, check=False
        )
        return result.stdout.strip() or None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


class GitHubClient:
    def __init__(self, token: str | None = None):
        self.token = token if token is not None else github_token()

    def _get(self, path: str) -> object:
        url = path if path.startswith("https://") else f"https://api.github.com{path}"
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "ownbox/0.1"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            message = exc.reason
            try:
                message = json.load(exc)["message"]
            except (ValueError, KeyError, AttributeError, TypeError):
                pass
            raise GitHubError(f"GitHub API error {exc.code}: {message}") from exc
        except urllib.error.URLError as exc:
            raise GitHubError(f"could not reach GitHub: {exc.reason}") from exc

    def current_user(self) -> str:
        if not self.token:
            raise GitHubError("no GitHub login found; run 'gh auth login' or set GH_TOKEN")
        data = self._get("/user")
        assert isinstance(data, dict)
        return str(data["login"])

    def repositories(self, owner: str) -> list[dict]:
        repos: list[dict] = []
        if self.token and owner.casefold() == self.current_user().casefold():
            path = "/user/repos?affiliation=owner&per_page=100&sort=updated"
        else:
            quoted = urllib.parse.quote(owner)
            path = f"/users/{quoted}/repos?per_page=100&sort=updated"
        page = 1
        while True:
            separator = "&" if "?" in path else "?"
            data = self._get(f"{path}{separator}page={page}")
            if not isinstance(data, list):
                raise GitHubError("unexpected repository response")
            repos.extend(item for item in data if not item.get("archived"))
            if len(data) < 100:
                return repos
            page += 1

    def manifest(self, full_name: str) -> Manifest | None:
        quoted = urllib.parse.quote(full_name, safe="/")
        try:
            data = self._get(f"/repos/{quoted}/contents/ownbox.yaml")
        except GitHubError as exc:
            if "error 404" in str(exc):
                return None
            raise
        if not isinstance(data, dict) or "content" not in data:
            return None
        raw = base64.b64decode(str(data["content"])).decode("utf-8")
        return Manifest.from_text(raw, full_name)

    def discover(self, owner: str) -> tuple[list[Manifest], list[str]]:
        repos = self.repositories(owner)
        manifests: list[Manifest] = []
        warnings: list[str] = []
        with ThreadPoolExecutor(max_workers=min(12, max(1, len(repos)))) as pool:
            futures = {pool.submit(self.manifest, repo["full_name"]): repo for repo in repos}
            for future in as_completed(futures):
                repo = futures[future]
                try:
                    manifest = future.result()
                    if manifest:
                        manifests.append(manifest)
                    else:
                        tags = list(repo.get("topics") or [])
                        if repo.get("language"):
                            tags.append(str(repo["language"]).casefold())
                        manifests.append(
                            Manifest(
                                name=repo["name"],
                                description=repo.get("description")
                                or f"GitHub repository {repo['full_name']}",
                                repo=repo["full_name"],
                                tags=tuple(dict.fromkeys(tags)),
                                homepage=repo.get("html_url"),
                            )
                        )
                except (GitHubError, ManifestError, UnicodeDecodeError) as exc:
                    warnings.append(f"{repo['full_name']}: {exc}")
        manifests.sort(key=lambda item: item.name.casefold())
        return manifests, warnings
