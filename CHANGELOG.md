# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.6.0] - 2026-08-19

### Added

- `ownbox update-all` updates every installed tool in one pass. Failures are
  isolated per tool, incomplete installations are skipped, and the command
  exits non-zero if anything failed.
- `ownbox rollback NAME [STEPS]` reverts a tool to a previously installed
  revision, re-running that revision's update commands under the usual
  approval prompt. Also available as `NAME rollback`, a new reserved word.
- `ownbox set KEY VALUE` and `ownbox settings` for configuration, with the
  first setting: `keep-history` (default 5, `0` disables), controlling how
  many prior revisions per tool stay available to roll back to.
- Update history is recorded per tool and surfaced in `NAME info` as the
  available rollback targets.

### Fixed

- `save_owner()` no longer rewrites the whole config file; config writes now
  merge, so the catalog owner and settings can coexist.

### Added

- Installs and updates now record the checked-out commit SHA. `ownbox list`
  shows the short revision and `<tool> info` shows the full one.
- Configurable subprocess timeouts for git operations and tool-authored
  lifecycle commands, via `OWNBOX_CLONE_TIMEOUT` and `OWNBOX_COMMAND_TIMEOUT`.
- `install()` accepts an optional `approve_commands` callback, matching
  `update()` and `uninstall()`, so library callers can gate setup commands.
- Test coverage for the GitHub API client, which previously had none.
- `CONTRIBUTING.md`, this changelog, and README sections for licensing and
  troubleshooting.
- CI now runs mypy and reports coverage, and caches pip downloads.

### Fixed

- A failed setup command no longer orphans the checkout. The installation is
  recorded as `incomplete` before setup runs, so `ownbox uninstall` can always
  clean it up; previously the directory was left untracked and unremovable.
- `ownbox update` now fetches, reads the incoming manifest, and asks for
  approval *before* fast-forwarding. Declining leaves the checkout completely
  untouched; previously the pull had already happened.
- A missing `git` (or other executable) now reports a readable error naming the
  program instead of an unhandled traceback.
- `installed.json` and the catalog cache are written atomically, so a crash or
  concurrent run can no longer truncate them. A corrupt state file now raises a
  clear error naming the file.
- Manifest validation rejects unsupported `install.platforms` values and unknown
  keys (with a suggestion for near-misses) instead of silently ignoring them.

### Changed

- `<tool> info` now prints the same manifest detail as catalog `info`, and the
  two share one implementation.

## [0.5.1] - 2026-08-16

### Fixed

- Installed tools now run with the working directory of the caller (the
  directory the launcher was invoked from) instead of the tool's checkout
  directory.

## [0.5.0] - 2026-08-16

### Added

- Support for multiple launchers per tool: a manifest's top-level `commands`
  mapping creates one launcher per key, with all launchers sharing the same
  checkout and lifecycle commands.

## [0.4.0] - 2026-08-16

### Added

- `ownbox uninstall` / `TOOL uninstall` (alias `remove`) to remove an
  installed tool's launcher and checkout, with `--keep-files` to keep the
  checkout while unregistering the launcher.
- Native `install.update` and `install.remove` manifest fields so apps can
  provide their own update and cleanup commands instead of relying on
  `install.setup` alone.
- `-y`/`--yes` flags on `update`/`upgrade` and `uninstall`/`remove` to approve
  their lifecycle commands non-interactively.
- `ownbox init --update` and `ownbox init --remove` flags for generating
  manifests with native update/remove commands.

### Changed

- `ownbox info` now also prints a tool's update and remove commands, not just
  setup.
- `ownbox init` now defaults `install.platforms` to the current platform
  instead of always defaulting to `linux`.

## [0.2.0] - 2026-08-14

### Added

- Transparent command launchers: installing a tool creates a launcher command
  that routes ordinary arguments to the manifest's `command` while reserving
  `update`, `uninstall`, `info`, and `where` for Ownbox itself (bypassable
  with `--`).

## [0.1.0] - 2026-08-14

### Added

- Initial release of Ownbox: `sync`, `search`, `info`, `install`/`add`,
  `list`/`ls`, `update`/`upgrade`, `run`, `init`, and `doctor` commands for
  discovering, installing, and running tools from `ownbox.yaml` manifests in
  GitHub repositories.
