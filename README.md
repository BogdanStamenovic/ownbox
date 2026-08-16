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
    windows: 'powershell.exe -File .\fiotransfer.ps1 fiotransfer'
  fioget:
    linux: ./ownbox.sh fioget
    darwin: ./ownbox.sh fioget
    windows: 'powershell.exe -File .\fiotransfer.ps1 fioget'
```

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
printcam info                  ->  Ownbox shows installation information
printcam where                 ->  Ownbox prints the checkout directory
printcam uninstall             ->  Ownbox removes the launcher and checkout
printcam remove                ->  Alias for uninstall, including app-native cleanup
```

Only `update`, `uninstall`, `remove`, `info`, and `where` are reserved. All other arguments pass through untouched.
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

## Where files go

- Tools: `$XDG_DATA_HOME/ownbox/tools` (usually `~/.local/share/ownbox/tools`)
- Launchers: `$OWNBOX_BIN_DIR` (usually `~/.local/bin`)
- Catalog: `$XDG_CACHE_HOME/ownbox/catalog.json`
- Config: `$XDG_CONFIG_HOME/ownbox/config.yaml`

On Windows, tools and `.cmd` launchers default to `%LOCALAPPDATA%\ownbox`, the catalog is under
`%LOCALAPPDATA%\ownbox\cache`, and configuration is under `%APPDATA%\ownbox`. Add
`%LOCALAPPDATA%\ownbox\bin` to `PATH`, or set `OWNBOX_BIN_DIR` to a directory already on `PATH`.

Run `ownbox doctor` if authentication or dependencies are not working.
