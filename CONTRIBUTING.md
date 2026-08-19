# Contributing to Ownbox

## Set up a development environment

Python 3.10+ and Git are required.

```bash
git clone https://github.com/BogdanStamenovic/ownbox.git
cd ownbox
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

On Windows PowerShell, use `.venv\Scripts\python.exe -m pip install -e ".[dev]"` instead.

The `dev` extra installs `pytest`, `pytest-cov`, `ruff`, and `mypy`.

## Run the checks

```bash
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/python -m mypy src/ownbox
```

CI runs the same checks (plus a coverage report) on Linux, macOS, and Windows across
Python 3.10 and 3.13, and must pass before a change is merged.

## Manifest and schema conventions

Contributors adding or changing tool manifests (`ownbox.yaml`) should follow the
conventions documented in `AGENTS.md`:

- `schema` is required and currently `1`.
- `name`, `description`, and one of `command`/`commands` are required; `tags`,
  `homepage`, and `install.platforms`/`install.setup`/`install.update`/`install.remove`
  are optional.
- `install.setup`, `install.update`, `install.remove`, and `command` each accept either a
  single list/string used on every platform, or a mapping with `linux`, `darwin`,
  `windows`, and optional `default` keys.
- Repositories with more than one executable should use a top-level `commands` mapping
  instead of `command`; each key becomes its own launcher, and all launchers from one
  manifest share a single checkout and lifecycle.
- `update`, `uninstall`, `remove`, `info`, and `where` are reserved launcher arguments;
  document any manifest examples accordingly and note that `--` bypasses routing to reach
  the underlying tool.
- Lifecycle commands are code from the target repository. Ownbox always displays them and
  asks for confirmation before running them (`--yes` skips the prompt); keep that behavior
  in mind when changing install/update/remove flows.

Generate a starter manifest with `ownbox init` in a tool repository, then edit it by hand
as needed; see `AGENTS.md` and the README for full examples.
