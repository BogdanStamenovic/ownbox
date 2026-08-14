# Ownbox

Ownbox turns your GitHub account into a searchable personal tool shelf. Every repository is
searchable and cloneable immediately. Put a small `ownbox.yaml` manifest in a repository to
also teach Ownbox how to set it up and which commands it exposes.

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

# Work with installed tools
ownbox list
ownbox update printcam
ownbox run printcam test
```

The first sync defaults to the GitHub account authenticated by `gh`. To use an organization
or another public account, run `ownbox sync --owner NAME`.

## Add a project

Run `ownbox init` in a repository, or create `ownbox.yaml` yourself:

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

commands:
  run: .venv/bin/python -m printcam
  test: .venv/bin/python -m pytest
```

Commit the file to the repository's default branch and run `ownbox sync`. The repository was
already searchable; its new setup and commands will now be available. No change to a central
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
| `commands` | no | Named commands available through `ownbox run` |

Setup commands are code from the repository. Ownbox displays them and asks for confirmation
before running them. Use `--yes` only for repositories you trust.

## Where files go

- Tools: `$XDG_DATA_HOME/ownbox/tools` (usually `~/.local/share/ownbox/tools`)
- Catalog: `$XDG_CACHE_HOME/ownbox/catalog.json`
- Config: `$XDG_CONFIG_HOME/ownbox/config.yaml`

Run `ownbox doctor` if authentication or dependencies are not working.
