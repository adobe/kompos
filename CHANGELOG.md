# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.11.0] - 2026-05-01

### Added
- **Helm overrides merge** — per-chart `overrides/{default,env,cluster}.yaml` merged on top
  of the bridge template. Merge order: bridge < default < env < cluster (wins).
  New config: `overrides_merge`, `overrides_subdir`, `bridge_filename`, `symlink_generated`.
- **Managed README** — `GenericRunner.write_managed_readme` reusable by all runners;
  helm runner writes pipeline diagrams from `data/templates/` markdown templates.
- **GenericRunner utilities** — `load_yaml_file`, `merge_configs` (delegates to himl).

### Changed
- **Dispatch moved to CompileRunner** — `GenericRunner` skips foreign compositions instead
  of auto-dispatching. Use `compile build` to run all.
- **Helm output** — compact chart list with `[bridge]`/`[overrides]` tags, structured sections.
- **`find_charts`** — discovers dirs with `bridge.yaml` or `overrides/` (was `values.yaml`).

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
