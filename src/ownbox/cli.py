from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from . import __version__
from .github import GitHubClient, GitHubError
from .manifest import Manifest, ManifestError, current_platform
from .store import (
    Catalog,
    bin_home,
    config_home,
    install,
    installations,
    launcher_path,
    new_catalog,
    resolve_installation,
    uninstall,
    update,
)

TOP_LEVEL_COMMANDS = {
    "sync",
    "search",
    "info",
    "install",
    "add",
    "uninstall",
    "remove",
    "list",
    "ls",
    "update",
    "upgrade",
    "run",
    "init",
    "doctor",
}


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


def confirm_commands(name: str, action: str, commands: tuple[str, ...], assume_yes: bool) -> bool:
    if not commands or assume_yes:
        return True
    print(f"Ownbox will run these {action} commands from the {name} checkout:")
    for command in commands:
        print(f"  $ {command}")
    if not sys.stdin.isatty():
        print(
            f"Use --yes to approve {action} commands in a non-interactive session.",
            file=sys.stderr,
        )
        return False
    return input("Continue? [y/N] ").strip().casefold() in {"y", "yes"}


def confirm_setup(tool: Manifest, assume_yes: bool) -> bool:
    return confirm_commands(tool.name, "setup", tool.setup, assume_yes)


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

    remove = sub.add_parser(
        "uninstall", aliases=["remove"], help="unregister a tool and remove its checkout"
    )
    remove.add_argument("name")
    remove.add_argument(
        "--keep-files", action="store_true", help="keep the checkout while removing the launcher"
    )
    remove.add_argument("-y", "--yes", action="store_true", help="approve app remove commands")

    sub.add_parser("list", aliases=["ls"], help="list installed tools")
    upgrade = sub.add_parser(
        "update", aliases=["upgrade"], help="pull and update an installed tool"
    )
    upgrade.add_argument("name")
    upgrade.add_argument("-y", "--yes", action="store_true", help="approve app update commands")

    run = sub.add_parser("run", help="run a named command from an installed tool")
    run.add_argument("name")
    run.add_argument("task")
    run.add_argument("args", nargs=argparse.REMAINDER)

    init = sub.add_parser("init", help="create an ownbox.yaml in the current repository")
    init.add_argument("--name", default=Path.cwd().name)
    init.add_argument("--description", default="TODO: describe this tool")
    init.add_argument(
        "--command",
        dest="entry_command",
        metavar="COMMAND",
        help="entry command that receives all non-Ownbox arguments",
    )
    init.add_argument(
        "--setup",
        action="append",
        default=[],
        metavar="COMMAND",
        help="setup command; repeat as needed",
    )
    init.add_argument(
        "--update",
        action="append",
        default=[],
        metavar="COMMAND",
        help="native update command; repeat as needed",
    )
    init.add_argument(
        "--remove",
        action="append",
        default=[],
        metavar="COMMAND",
        help="native cleanup command; repeat as needed",
    )

    sub.add_parser("doctor", help="check local dependencies and GitHub login")
    return parser


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if raw_args and not raw_args[0].startswith("-") and raw_args[0] not in TOP_LEVEL_COMMANDS:
        return dispatch_tool(raw_args[0], raw_args[1:])
    args = build_parser().parse_args(raw_args)
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
            if tool.update:
                print("Update:")
                for command in tool.update:
                    print(f"  $ {command}")
            if tool.remove:
                print("Remove:")
                for command in tool.remove:
                    print(f"  $ {command}")
            if tool.command:
                print(f"Entry command: {tool.command}")
            if tool.commands:
                print("Commands:")
                for name, command in tool.commands.items():
                    print(f"  {name}: {command}")
        elif args.command in {"install", "add"}:
            tool = get_catalog().get(args.name)
            if not confirm_setup(tool, args.yes):
                return 2
            target = install(tool, args.path)
            print(f"Installed {tool.name} at {target}")
            for name in tool.entry_commands() or {tool.name: ""}:
                print(f"Command: {launcher_path(name)}")
            if str(bin_home()) not in os.environ.get("PATH", "").split(os.pathsep):
                print(f"Add {bin_home()} to PATH to invoke '{tool.name}' directly.")
        elif args.command in {"uninstall", "remove"}:
            target = uninstall(
                args.name,
                keep_files=args.keep_files,
                approve_commands=lambda commands: confirm_commands(
                    args.name, "remove", commands, args.yes
                ),
            )
            if args.keep_files:
                print(f"Uninstalled {args.name}; kept checkout at {target}")
            else:
                print(f"Uninstalled {args.name}; removed checkout at {target}")
        elif args.command in {"list", "ls"}:
            state = installations()
            if not state:
                print("No tools installed yet.")
            for name, item in sorted(state.items()):
                print(f"{name:<24} {item['path']}")
        elif args.command in {"update", "upgrade"}:
            target = update(
                args.name,
                approve_commands=lambda commands: confirm_commands(
                    args.name, "update", commands, args.yes
                ),
            )
            print(f"Updated {args.name} at {target}")
        elif args.command == "run":
            return dispatch_tool(args.name, [args.task, *args.args])
        elif args.command == "init":
            path = Path("ownbox.yaml")
            if path.exists():
                raise RuntimeError("ownbox.yaml already exists")
            command = args.entry_command
            if not command and sys.stdin.isatty():
                command = input("Project entry command: ").strip()
            if not command:
                raise RuntimeError("an entry command is required; use --command 'your command'")
            data = {
                "schema": 1,
                "name": args.name,
                "description": args.description,
                "tags": [],
                "install": {
                    "platforms": [current_platform()],
                    "setup": args.setup,
                    "update": args.update,
                    "remove": args.remove,
                },
                "command": command,
            }
            path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
            print(f"Created {path}; edit it, commit it, then run 'ownbox sync'.")
        elif args.command == "doctor":
            print(f"git: {'ok' if shutil.which('git') else 'missing'}")
            print(f"gh:  {'ok' if shutil.which('gh') else 'missing (public repos only)'}")
            on_path = str(bin_home()) in os.environ.get("PATH", "").split(os.pathsep)
            print(f"command directory: {bin_home()} ({'on PATH' if on_path else 'not on PATH'})")
            try:
                user = GitHubClient().current_user()
                print(f"GitHub login: {user}")
            except GitHubError as exc:
                print(f"GitHub login: unavailable ({exc})")
                return 1
        return 0
    except (
        GitHubError,
        ManifestError,
        RuntimeError,
        KeyError,
        subprocess.CalledProcessError,
    ) as exc:
        if isinstance(exc, KeyError):
            message = f"tool not found: {exc.args[0]}; run 'ownbox search --refresh'"
        else:
            message = str(exc)
        print(f"error: {message}", file=sys.stderr)
        return 1


def shlex_quote(value: str) -> str:
    return shlex.quote(value)


def shell_join(arguments: list[str]) -> str:
    if current_platform() == "windows":
        return subprocess.list2cmdline(arguments)
    return " ".join(shlex_quote(value) for value in arguments)


def resolve_entry_executable(command: str, checkout: Path) -> str:
    """Make a checkout-relative entry executable usable from the caller's directory."""
    match = re.match(r'^\s*(?:"(?:[^"\\]|\\.)*"|\'(?:[^\']*)\'|[^\s]+)', command)
    if not match:
        return command
    executable = match.group(0).strip()
    try:
        parsed = shlex.split(executable, posix=current_platform() != "windows")[0]
    except (ValueError, IndexError):
        return command
    parsed = parsed.strip('"')
    if Path(parsed).is_absolute() or not (
        parsed.startswith(".") or "/" in parsed or "\\" in parsed
    ):
        return command
    resolved = str(checkout / parsed)
    quoted = (
        subprocess.list2cmdline([resolved])
        if current_platform() == "windows"
        else shlex_quote(resolved)
    )
    return command[: match.start()] + quoted + command[match.end() :]


def installed_tool(name: str) -> tuple[str, dict]:
    return resolve_installation(installations(), name)


def dispatch_tool(name: str, arguments: list[str]) -> int:
    try:
        installed_name, item = installed_tool(name)
        target = Path(item["path"])
        action = arguments[0] if arguments else None
        if action == "update":
            assume_yes = arguments[1:] in (["-y"], ["--yes"])
            if arguments[1:] and not assume_yes:
                raise RuntimeError("usage: <app> update [--yes]")
            updated = update(
                installed_name,
                approve_commands=lambda commands: confirm_commands(
                    installed_name, "update", commands, assume_yes
                ),
            )
            print(f"Updated {installed_name} at {updated}")
            return 0
        if action in {"uninstall", "remove"}:
            assume_yes = arguments[1:] in (["-y"], ["--yes"])
            if arguments[1:] and not assume_yes:
                raise RuntimeError(f"usage: <app> {action} [--yes]")
            removed = uninstall(
                installed_name,
                approve_commands=lambda commands: confirm_commands(
                    installed_name, "remove", commands, assume_yes
                ),
            )
            print(f"Uninstalled {installed_name}; removed checkout at {removed}")
            return 0
        if action == "where":
            print(target)
            return 0
        manifest = Manifest.from_path(target / "ownbox.yaml", item["repo"])
        if action == "info":
            print(f"{installed_name} — {manifest.description}")
            print(f"Repository: https://github.com/{item['repo']}")
            print(f"Installed: {target}")
            return 0
        command = manifest.command_for(name)
        if not command:
            raise RuntimeError(
                f"{name!r} has no entry command; add it to 'command' or 'commands' in ownbox.yaml"
            )
        command = resolve_entry_executable(command, target)
        if arguments:
            command += " " + shell_join(arguments)
        environment = os.environ.copy()
        environment["OWNBOX_TOOL_DIR"] = str(target)
        return subprocess.run(
            command, cwd=Path.cwd(), env=environment, shell=True, check=False
        ).returncode
    except (ManifestError, RuntimeError, KeyError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
