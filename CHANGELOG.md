# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.12.0] - 2026-06-11

### Added
- **`external` composition / runner** — plugin host for repo-local transforms: invoke a Python
  `entrypoint` or subprocess `command`, pass only declared `inputs`, write declared `outputs`
  under `<base>/<output_subdir>/<instance>/`. Supports `result_key`, YAML `header_key` comment
  banners, and `compile build` dispatch.

## [0.11.8] - 2026-06-09

### Changed
- **`composition.enabled: false` now pauses TFE workspaces instead of fully skipping them.**
  Previously a disabled composition was skipped entirely, so a workspace that already existed
  was left frozen at its last-generated definition — and a workspace template that derives
  `terraform_automation_enabled` from `composition.enabled` never got the chance to write the
  paused value. The TFE runner now still (re)generates the **workspace definition** for a
  disabled composition (via a new `generate_disabled()` hook) while skipping its tfvars +
  terraform module, so the workspace carries `terraform_automation_enabled: false` and TFE
  actually pauses it, with the infra config left frozen. Non-TFE runners (terraform, helm,
  manual) keep the default full skip. `compile build` now dispatches disabled compositions too
  so they reach this hook.

### Fixed
- **`compositions.order.terraform` is now optional** — the config schema previously required a
  non-empty `terraform` entry under `compositions.order`, forcing tfe-only repos to declare a
  dummy terraform order just to pass validation. The `required: ["terraform"]` constraint on
  `order` is dropped; if `terraform` is present it must still be a non-empty array of strings.
  `composition_order()` already returns `[]` for a missing runner, so routing is unaffected.

## [0.11.6] - 2026-06-03

### Added
- **`composition.enabled`** — when `false` in layered config, `compile build` and individual
  runners skip generation for that composition root. Disabled compositions are still in
  configs/, so they stay in the `--prune` live set: their existing `generated/` artifacts are
  frozen (skip ≠ delete). `--prune` only removes artifacts for compositions removed from configs/.
- **`manual` composition / runner** — materializes hand-declared artifacts that have no
  upstream generator (e.g. a mock terraform-outputs file for a cluster whose infra is managed
  elsewhere). Declared under `composition.files: [{path, from_key|content}]`; the runner writes
  each to `<base>/<output_subdir>/<instance>/<path>` (`output_subdir` defaults to `clusters`).
  This makes such files config-as-code and prune-aware instead of stray hand-edited files in
  the generated tree.

### Changed
- **TFE unresolved instance** — when `composition.instance` cannot be resolved, the runner
  now prints one actionable error (instead of a repeated low-level warning) and exits with
  code 1 instead of silently succeeding with 0 files generated. `composition.enabled: false`
  is reported with a single skip line.

### Fixed
- **Redundant config reads** — `get_raw_config` is memoized per `(config_path, composition)`,
  so the enabled check, ownership check, and generation no longer re-run the full himl merge.
- **`--prune` deleting helm-only clusters** — `generated/clusters/<name>` is shared by the tfe
  `cluster` output (`tfe/`) and the `helm-values` output (`helm-values/`). Prune scanned that
  directory per-runner, so the tfe cluster pass deleted any dir absent from the tfe live set —
  wiping helm-only clusters (helm-values composition, no tfe cluster). Prune now tests entries
  against the **union** of all runners' live instances, so a dir is kept if any composition
  still claims it; only instances removed from configs/ entirely are pruned.

## [0.11.0] - 2026-05-01

### Added
- **Helm overrides merge** — optional per-chart `overrides/` directory with `default.yaml`,
  `{env}.yaml`, and `{cluster}.yaml` files merged on top of the bridge template output.
  Merge order: bridge (interpolated) < default < env < cluster (wins).
  Enabled via `helm.config.overrides_merge: true` in `.komposconfig.yaml`.
- **Bridge template rename** — configurable bridge filename via `helm.config.bridge_filename`
  (default: `bridge.yaml`). Replaces `values.yaml` to clearly distinguish bridge templates
  from Helm chart defaults.
- **Symlink generation** — optional `helm.config.symlink_generated: true` creates symlinks
  in `charts/{chart}/generated/` pointing to the source of truth in `generated/clusters/`.
- **Managed README generation** — `write_managed_readme` on `GenericRunner`, reusable by
  all runners. Helm runner writes pipeline diagrams from markdown templates in
  `data/templates/helm-readme.md` and `data/templates/helm-chart-readme.md`.
- **`GenericRunner.load_yaml_file`** — shared YAML loading utility for all runners.
- **`GenericRunner.merge_configs`** — single entry point for all config merging, delegates
  to himl's `ConfigGenerator.merge_value` for consistent merge behavior.

### Changed
- **Dispatch removed from GenericRunner** — auto-dispatch of foreign compositions moved
  exclusively to `CompileRunner`. Individual runners now skip compositions they don't own
  with a log message suggesting `compile build`.
- **Helm console output** — compact chart list with `[bridge]`/`[overrides]` tags, structured
  Context/Output/Charts sections, override files shown as indented children.
- **`find_charts`** — discovers chart dirs with `bridge.yaml` or `overrides/` directory
  (previously required `values.yaml`).

### Fixed
- Removed bogus `validate=` kwarg passed to `resolve_interpolations` static method in helm runner.

## [0.10.1] - 2026-03-27

### Added
- **TFE runner**: `nested_subdir` config option in `generation_config` — nests all TFE-generated
  files under a named subdirectory inside the composition instance dir.
  Example: `nested_subdir: "tfe"` → `generated/clusters/{instance}/tfe/` instead of `generated/clusters/{instance}/`.
  Useful when multiple generators share the same instance directory (helm values, infra outputs, terraform).
- **Example** `06-komposconfig` — dedicated example covering all `.komposconfig.yaml` features:
  composition ordering, output_subdir routing, system_keys, and nested_subdir.
- **Test** `3.4` — integration test for `nested_subdir` output routing in the KOMPOSCONFIG section.

### Fixed
- `get_kompos_setting` (dotted path traversal) used consistently for nested config keys in the TFE runner,
  replacing `get_runtime_setting` which only did flat dict lookup.

## [0.10.0] - 2026-01-29

### Added
- **Helm values runner** (`kompos <path> helm generate`) — renders himl-templated Helm values
  per cluster, merging the kompos hierarchy with TFE outputs (`global.infra.*`).
  - `helm generate` — renders all enabled charts to `argoapps/{chart}.yaml`
  - `helm generate --dry-run` — prints rendered output without writing files
  - `helm generate --chart-dir PATH` — single-chart mode for local development
  - `helm list` — shows enabled/disabled/untracked charts with versions
  - `__helm_values__` internal key isolates chart values from kompos context during interpolation
  - `prune_argoapps` — removes stale files for disabled/removed charts
- **Example** `05-helm-values` — end-to-end example with chart registry, global values, and cluster overrides.
- **Tests** group 6 — helm runner integration tests (help, list, generate dry-run, file writes, single chart).

### Changed
- `get_raw_config` now always passes `filters=[]` and `exclude_keys=[]` to ensure the full config
  is available for interpolation in all runners.
- Updated examples `04-tfe-multi-cluster` with improved documentation.

## [0.9.4] - 2026-01-27

### Added
- Initial TFE multi-cluster example (`04-tfe-multi-cluster`).
- Improved console output formatting across all runners.
- `GenericRunner.ensure_directory` shared utility for consistent directory creation.
- `GenericRunner.resolve_interpolations` for in-place himl interpolation outside the config walk.

### Fixed
- Console display bug in runner output formatting.
