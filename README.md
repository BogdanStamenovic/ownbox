# Ownbox

Ownbox turns your GitHub account into a searchable personal tool shelf. Every repository is
searchable and cloneable immediately. Put a small `ownbox.yaml` manifest in a repository to
also teach Ownbox how to set it up and which executable receives its arguments.

It works with public and private repositories and has no server or central registry.
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
  --setup '.venv/bin/pip install -e .'
```

You can also create `ownbox.yaml` yourself:

```yaml
schema: 1
name: printcam
description: Set up a small Linux print camera automatically.
tags: [camera, linux, raspberry-pi]

install:
  platforms: [linux]
  setup:
    - python -m venv .venv
    - .venv/bin/pip install -e .

command: .venv/bin/python -m printcam
```

After installation, Ownbox creates `~/.local/bin/printcam`. The launcher always goes through
Ownbox, but normal arguments pass through to the configured command:

```text
printcam photo --output a.jpg  ->  .venv/bin/python -m printcam photo --output a.jpg
printcam --help                ->  .venv/bin/python -m printcam --help
printcam update                ->  Ownbox updates the Git checkout and reruns setup
printcam info                  ->  Ownbox shows installation information
printcam where                 ->  Ownbox prints the checkout directory
printcam uninstall             ->  Ownbox removes the launcher and checkout
```

Only `update`, `uninstall`, `info`, and `where` are reserved. All other arguments pass through untouched.
If the underlying app itself needs one of those words, use `--` to bypass routing—for example,
`printcam -- update` passes `-- update` to PrintCAM.

Use `ownbox uninstall printcam --keep-files` to unregister the tool and remove its launcher
without deleting its checkout.

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
| `install.setup` | no | Shell commands run in order after cloning |
| `command` | for launchers | Entry command that receives normal CLI arguments |

Setup commands are code from the repository. Ownbox displays them and asks for confirmation
before running them. Use `--yes` only for repositories you trust.

## Where files go

- Tools: `$XDG_DATA_HOME/ownbox/tools` (usually `~/.local/share/ownbox/tools`)
- Launchers: `$OWNBOX_BIN_DIR` (usually `~/.local/bin`)
- Catalog: `$XDG_CACHE_HOME/ownbox/catalog.json`
- Config: `$XDG_CONFIG_HOME/ownbox/config.yaml`

Run `ownbox doctor` if authentication or dependencies are not working.
