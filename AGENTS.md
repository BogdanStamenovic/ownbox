# Working with Ownbox tools

## Register a tool

Every repository in the configured GitHub account is searchable. To make a repository
installable and runnable, add an `ownbox.yaml` manifest to its default branch. From the tool
repository, generate one with:

```bash
ownbox init --command '.venv/bin/python -m my_tool' \
  --setup 'python -m venv .venv' \
  --setup '.venv/bin/pip install -e .'
```

Edit the generated name, description, tags, supported platforms, lifecycle commands, and entry
command as needed. For cross-platform tools, `install.setup`, `install.update`, `install.remove`,
and `command` may use `linux`, `darwin`, `windows`, and optional `default` mappings. If
`install.update` is absent, Ownbox reruns `install.setup` after pulling. `install.remove` runs before
the checkout is deleted. Commit and push `ownbox.yaml`, then refresh
the local catalog:

```bash
ownbox sync
```

No central registry is involved: GitHub repositories and their manifests are the registry.
Use `ownbox sync --owner NAME` to select a different user or organization.

## Find, inspect, and install a tool

```bash
ownbox search
ownbox search QUERY
ownbox info TOOL
ownbox install TOOL
```

Ownbox shows manifest setup commands before executing them. In a trusted, non-interactive
environment, approve them with `ownbox install TOOL --yes`. A custom checkout location can be
selected with `ownbox install TOOL --path PATH`.

## Run and manage an installed tool

The tool name becomes a launcher command, and ordinary arguments are forwarded to the manifest's
`command`:

```bash
TOOL ARGS...
ownbox run TOOL TASK ARGS...
ownbox list
TOOL info
TOOL where
TOOL update
```

`update`, `uninstall`, `info`, and `where` are reserved launcher actions. Prefix a reserved word
with `--` when it must go to the underlying tool, for example `TOOL -- update`.

## Uninstall a tool

Either form removes the generated launcher, cloned checkout, and installation record:

```bash
ownbox uninstall TOOL
TOOL uninstall
```

To unregister the tool and remove only its launcher while retaining the checkout, use:

```bash
ownbox uninstall TOOL --keep-files
```

Uninstalling does not remove the source GitHub repository or its catalog entry. Remove or rename
`ownbox.yaml` in that repository if it should no longer be advertised as an installable tool, then
run `ownbox sync` again.
