# Ownbox

Ownbox turns your GitHub account into a searchable personal tool shelf. Every repository is
searchable and cloneable immediately. Put a small `ownbox.yaml` manifest in a repository to
also teach Ownbox how to set it up and which executable receives its arguments.

It works on Linux, macOS, and Windows with public and private repositories and has no server or central registry.
Your GitHub account is the source of truth; the local catalog is just a fast cache.

## Install

Python 3.10+ and Git are required. The GitHub CLI is recommended for authentication and
private repositories.

```bash
gh auth login
pipx install git+https://github.com/BogdanStamenovic/ownbox.git
```

For development:

```bash
git clone https://github.com/BogdanStamenovic/ownbox.git
cd ownbox
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

On Windows PowerShell, use:

```powershell
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Use

```bash
# Scan your GitHub repositories and read any ownbox.yaml files
ownbox sync

# Search everything or narrow it down
ownbox search
ownbox search raspberry pi
ownbox search camera

# Review and install a tool
ownbox info printcam
ownbox install printcam

# Installed tools become commands routed through Ownbox
ownbox list
printcam photo --output latest.jpg
printcam update
printcam info
ownbox uninstall printcam

# Update every installed tool in one pass
ownbox update-all

# Go back to the previous revision (or further back with a step count)
ownbox rollback printcam
ownbox rollback printcam 2
```

The first sync defaults to the GitHub account authenticated by `gh`. To use an organization
or another public account, run `ownbox sync --owner NAME`.

## Add a project

Run `ownbox init` in a repository. The entry command is required because it receives everything
that Ownbox does not handle itself:

```bash
ownbox init --command '.venv/bin/python -m printcam' \
  --setup 'python -m venv .venv' \
  --setup '.venv/bin/pip install -e .' \
  --update '.venv/bin/pip install -e .' \
  --remove '.venv/bin/python -m printcam cleanup'
```

You can also create `ownbox.yaml` yourself:

```yaml
schema: 1
name: printcam
description: Set up a small Linux print camera automatically.
tags: [camera, linux, raspberry-pi]

install:
  platforms: [linux, darwin, windows]
  setup:
    linux:
      - python -m venv .venv
      - .venv/bin/python -m pip install -e .
    darwin:
      - python -m venv .venv
      - .venv/bin/python -m pip install -e .
    windows:
      - python -m venv .venv
      - '.venv\Scripts\python.exe -m pip install -e .'

command:
  linux: .venv/bin/python -m printcam
  darwin: .venv/bin/python -m printcam
  windows: '.venv\Scripts\python.exe -m printcam'
```

Repositories that provide more than one executable can use `commands` instead.
Ownbox creates a launcher for every key, while all launchers share one checkout
and lifecycle:

```yaml
commands:
  fiotransfer:
    linux: ./ownbox.sh fiotransfer
    darwin: ./ownbox.sh fiotransfer
    windows: 'powershell.exe -File "$env:OWNBOX_TOOL_DIR\fiotransfer.ps1" fiotransfer'
  fioget:
    linux: ./ownbox.sh fioget
    darwin: ./ownbox.sh fioget
    windows: 'powershell.exe -File "$env:OWNBOX_TOOL_DIR\fiotransfer.ps1" fioget'
```

Tools run with the working directory from which the launcher (or `ownbox run`) was invoked.
Checkout-relative entry executables such as `.venv/bin/python` and `./ownbox.sh` are resolved
automatically. The checkout path is also available to entry commands as `OWNBOX_TOOL_DIR`.

`install.setup` may be either one list used everywhere or a mapping with `linux`, `darwin`,
`windows`, and optional `default` keys. `command` similarly accepts either one string or a
platform mapping. Use mappings whenever virtual-environment executable paths differ.

After installation, Ownbox creates `~/.local/bin/printcam` on Linux/macOS or
`%LOCALAPPDATA%\ownbox\bin\printcam.cmd` on Windows. The launcher always goes through Ownbox,
but normal arguments pass through to the configured command:

```text
printcam photo --output a.jpg  ->  .venv/bin/python -m printcam photo --output a.jpg
printcam --help                ->  .venv/bin/python -m printcam --help
printcam update                ->  Ownbox pulls and runs its update commands (or setup fallback)
printcam rollback              ->  Ownbox reverts the checkout to a previous revision
printcam info                  ->  Ownbox shows installation information
printcam where                 ->  Ownbox prints the checkout directory
printcam uninstall             ->  Ownbox removes the launcher and checkout
printcam remove                ->  Alias for uninstall, including app-native cleanup
```

Only `update`, `rollback`, `uninstall`, `remove`, `info`, and `where` are reserved. All other arguments pass through untouched.
If the underlying app itself needs one of those words, use `--` to bypass routing—for example,
`printcam -- update` passes `-- update` to PrintCAM.

Use `ownbox uninstall printcam --keep-files` to unregister the tool and remove its launcher
without deleting its checkout.

Apps can provide native update and removal commands alongside setup:

```yaml
install:
  setup: [python -m pip install -e .]
  update: [python -m pip install -U -e .]
  remove: [python -m printcam cleanup]
```

All three fields accept platform mappings. `ownbox update printcam` pulls with a fast-forward-only
Git update, then runs `install.update`. Older manifests without it continue to rerun
`install.setup`. `ownbox uninstall printcam` and `printcam remove` run `install.remove` before
removing the launcher and checkout. Ownbox displays lifecycle commands for approval; pass `--yes`
only for repositories you trust. If a remove command fails, Ownbox leaves the app installed.

Commit the file to the repository's default branch and run `ownbox sync`. The repository was
already searchable; its new setup and entry command will now be available. No change to a central
registry is needed.

### Manifest fields

| Field | Required | Meaning |
| --- | --- | --- |
| `schema` | yes | Manifest version; currently `1` |
| `name` | yes | Unique CLI-friendly tool name |
| `description` | yes | Searchable one-line summary |
| `tags` | no | Search terms such as `python`, `cli`, or `raspberry-pi` |
| `homepage` | no | Project or documentation URL |
| `install.platforms` | no | Any of `linux`, `darwin`, or `windows` |
| `install.setup` | no | Setup-command list, or mapping by platform |
| `install.update` | no | Native update-command list, or mapping by platform |
| `install.remove` | no | Native cleanup-command list, or mapping by platform |
| `command` | one entry form required | Single entry command string, or mapping by platform |
| `commands` | one entry form required | Launcher-name map whose values are commands or platform mappings |

Lifecycle commands are code from the repository. Ownbox displays them and asks for confirmation
before running them. Use `--yes` only for repositories you trust.

## Updating and rolling back

`ownbox update NAME` fetches, shows you the update commands from the incoming revision,
and only fast-forwards the checkout once you approve them. Declining leaves the checkout
exactly as it was.

`ownbox update-all` runs that over every installed tool. A tool that fails does not stop
the rest; incomplete installations are skipped, and the command exits non-zero if anything
failed.

Ownbox records the commit each tool is on, so `ownbox list` shows the short revision and
`NAME info` shows the full one along with the revisions available to roll back to.

`ownbox rollback NAME [STEPS]` reverts to a previously installed revision, defaulting to
one step back. It re-runs that revision's update commands (with the same approval prompt)
so the checkout is rebuilt to match. Rollback is a `git reset --hard`, so it refuses to run
when tracked files have uncommitted changes unless you pass `--force`; untracked build
artifacts are left alone and do not block it.

Rolling back consumes history: after `ownbox rollback printcam 2`, those two entries are
gone and moving forward again is just `ownbox update printcam`.

## Settings

```bash
ownbox settings                  # show every setting and its current value
ownbox set keep-history 10       # keep 10 prior revisions per tool
```

| Setting | Default | Meaning |
| --- | --- | --- |
| `keep-history` | `5` | How many prior revisions per tool stay available to `ownbox rollback`. `0` disables history. |

Settings are stored alongside the catalog owner in `config.yaml` in the config directory
described below. `keep-history` caps how many revisions Ownbox *remembers* as rollback
targets, not how much disk is used—the checkout is an ordinary git clone, so every revision
is present regardless.

## Where files go

- Tools: `$XDG_DATA_HOME/ownbox/tools` (usually `~/.local/share/ownbox/tools`)
- Launchers: `$OWNBOX_BIN_DIR` (usually `~/.local/bin`)
- Catalog: `$XDG_CACHE_HOME/ownbox/catalog.json`
- Config: `$XDG_CONFIG_HOME/ownbox/config.yaml`

On Windows, tools and `.cmd` launchers default to `%LOCALAPPDATA%\ownbox`, the catalog is under
`%LOCALAPPDATA%\ownbox\cache`, and configuration is under `%APPDATA%\ownbox`. Add
`%LOCALAPPDATA%\ownbox\bin` to `PATH`, or set `OWNBOX_BIN_DIR` to a directory already on `PATH`.

Run `ownbox doctor` if authentication or dependencies are not working.

## Troubleshooting

Run `ownbox doctor` first. It reports whether `git` and `gh` are on `PATH`, whether the
launcher directory is on `PATH`, and whether a GitHub login was found.

**GitHub authentication failures** ("no GitHub login found; run 'gh auth login' or set
GH_TOKEN"): Ownbox looks for a `GH_TOKEN` or `GITHUB_TOKEN` environment variable first,
then falls back to `gh auth token`. Run `gh auth login`, or export `GH_TOKEN`/`GITHUB_TOKEN`
with a personal access token, then retry.

**GitHub API rate limits**: unauthenticated requests to the GitHub API are limited to 60
requests per hour; an authenticated `gh` login or token raises that substantially. If
`ownbox sync` or `ownbox search --refresh` reports a GitHub API error, authenticate as
above and try again once the rate limit window resets.

**Other GitHub API errors**: Ownbox surfaces the GitHub API's own error message (for
example, an unknown owner or a network failure reaching `api.github.com`). Re-run
`ownbox doctor` to confirm connectivity and login state.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to set up a development environment, run
tests, and the manifest conventions to follow.

## License

Ownbox is released under the [MIT License](LICENSE).
