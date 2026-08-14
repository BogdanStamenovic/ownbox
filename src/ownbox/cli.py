from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from . import __version__
from .github import GitHubClient, GitHubError
from .manifest import Manifest, ManifestError
from .store import Catalog, config_home, install, installations, new_catalog, update


def owner_from_config() -> str | None:
    path = config_home() / "config.yaml"
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("owner")


def save_owner(owner: str) -> None:
    path = config_home() / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"owner": owner}, sort_keys=False), encoding="utf-8")


def get_catalog(refresh: bool = False, owner: str | None = None) -> Catalog:
    catalog = Catalog.load()
    if catalog and not refresh and (not owner or catalog.owner.casefold() == owner.casefold()):
        return catalog
    client = GitHubClient()
    resolved_owner = owner or owner_from_config() or client.current_user()
    tools, warnings = client.discover(resolved_owner)
    catalog = new_catalog(resolved_owner, tools)
    catalog.save()
    save_owner(resolved_owner)
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return catalog


def print_tools(tools: list[Manifest]) -> None:
    if not tools:
        print("No matching tools found.")
        return
    width = min(28, max(len(tool.name) for tool in tools))
    for tool in tools:
        tags = f"  [{', '.join(tool.tags)}]" if tool.tags else ""
        print(f"{tool.name:<{width}}  {tool.description}{tags}")


def confirm_setup(tool: Manifest, assume_yes: bool) -> bool:
    if not tool.setup or assume_yes:
        return True
    print(f"Ownbox will run these commands from the cloned {tool.name} directory:")
    for command in tool.setup:
        print(f"  $ {command}")
    if not sys.stdin.isatty():
        print("Use --yes to approve setup commands in a non-interactive session.", file=sys.stderr)
        return False
    return input("Continue? [y/N] ").strip().casefold() in {"y", "yes"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ownbox", description="Your personal GitHub tool shelf")
    parser.add_argument("--version", action="version", version=f"ownbox {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="scan GitHub and refresh the local catalog")
    sync.add_argument("--owner", help="GitHub user or organization (defaults to your login)")

    search = sub.add_parser("search", help="search the catalog")
    search.add_argument("query", nargs="*", help="words in the name, description, or tags")
    search.add_argument("--refresh", action="store_true", help="refresh from GitHub first")

    info = sub.add_parser("info", help="show a tool and its setup commands")
    info.add_argument("name")

    add = sub.add_parser("install", aliases=["add"], help="clone and set up a tool")
    add.add_argument("name")
    add.add_argument("--path", type=Path, help="custom clone destination")
    add.add_argument("-y", "--yes", action="store_true", help="approve manifest setup commands")

    sub.add_parser("list", aliases=["ls"], help="list installed tools")
    upgrade = sub.add_parser("update", aliases=["upgrade"], help="pull and set up an installed tool")
    upgrade.add_argument("name")

    run = sub.add_parser("run", help="run a named command from an installed tool")
    run.add_argument("name")
    run.add_argument("task")
    run.add_argument("args", nargs=argparse.REMAINDER)

    init = sub.add_parser("init", help="create an ownbox.yaml in the current repository")
    init.add_argument("--name", default=Path.cwd().name)
    init.add_argument("--description", default="TODO: describe this tool")

    sub.add_parser("doctor", help="check local dependencies and GitHub login")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "sync":
            catalog = get_catalog(refresh=True, owner=args.owner)
            print(f"Synced {len(catalog.tools)} tools from {catalog.owner}.")
        elif args.command == "search":
            catalog = get_catalog(refresh=args.refresh)
            print_tools(catalog.find(" ".join(args.query)) if args.query else catalog.tools)
        elif args.command == "info":
            tool = get_catalog().get(args.name)
            print(f"{tool.name} — {tool.description}\nRepository: https://github.com/{tool.repo}")
            if tool.tags:
                print(f"Tags: {', '.join(tool.tags)}")
            if tool.platforms:
                print(f"Platforms: {', '.join(tool.platforms)}")
            if tool.setup:
                print("Setup:")
                for command in tool.setup:
                    print(f"  $ {command}")
            if tool.commands:
                print("Commands:")
                for name, command in tool.commands.items():
                    print(f"  {name:<14} {command}")
        elif args.command in {"install", "add"}:
            tool = get_catalog().get(args.name)
            if not confirm_setup(tool, args.yes):
                return 2
            target = install(tool, args.path)
            print(f"Installed {tool.name} at {target}")
        elif args.command in {"list", "ls"}:
            state = installations()
            if not state:
                print("No tools installed yet.")
            for name, item in sorted(state.items()):
                print(f"{name:<24} {item['path']}")
        elif args.command in {"update", "upgrade"}:
            target = update(args.name)
            print(f"Updated {args.name} at {target}")
        elif args.command == "run":
            state = installations()
            if args.name not in state:
                raise RuntimeError(f"{args.name!r} is not installed")
            target = Path(state[args.name]["path"])
            manifest = Manifest.from_path(target / "ownbox.yaml", state[args.name]["repo"])
            if args.task not in manifest.commands:
                raise RuntimeError(f"unknown command {args.task!r}; choose: {', '.join(manifest.commands)}")
            command = manifest.commands[args.task]
            if args.args:
                command += " " + " ".join(shlex_quote(value) for value in args.args)
            return subprocess.run(command, cwd=target, shell=True, check=False).returncode
        elif args.command == "init":
            path = Path("ownbox.yaml")
            if path.exists():
                raise RuntimeError("ownbox.yaml already exists")
            data = {
                "schema": 1,
                "name": args.name,
                "description": args.description,
                "tags": [],
                "install": {"platforms": ["linux"], "setup": []},
                "commands": {},
            }
            path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
            print(f"Created {path}; edit it, commit it, then run 'ownbox sync'.")
        elif args.command == "doctor":
            print(f"git: {'ok' if shutil.which('git') else 'missing'}")
            print(f"gh:  {'ok' if shutil.which('gh') else 'missing (public repos only)'}")
            try:
                user = GitHubClient().current_user()
                print(f"GitHub login: {user}")
            except GitHubError as exc:
                print(f"GitHub login: unavailable ({exc})")
                return 1
        return 0
    except (GitHubError, ManifestError, RuntimeError, KeyError, subprocess.CalledProcessError) as exc:
        if isinstance(exc, KeyError):
            message = f"tool not found: {exc.args[0]}; run 'ownbox search --refresh'"
        else:
            message = str(exc)
        print(f"error: {message}", file=sys.stderr)
        return 1


def shlex_quote(value: str) -> str:
    import shlex

    return shlex.quote(value)


if __name__ == "__main__":
    raise SystemExit(main())
