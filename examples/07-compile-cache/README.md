# Compile Cache and Plugin Mutation

This example uses only the `external` and `manual` runners. It needs Kompos, but
no cloud credentials, Terraform, Helm, network access or additional dependencies.

Three compositions share a small hierarchy:

```text
configs/
  defaults.yaml                         # project, feature default and report interpolation
  team=demo/
    shared.yaml                         # initial message and replica count
    composition=refresh/plugin.yaml     # external plugin configuration
    consumer=alpha/composition=report/report.yaml
    consumer=beta/composition=report/report.yaml
plugins/
  cache_demo_plugin.py
```

## Run in a copy

The plugin deliberately changes an inherited input file, so use a disposable
copy to keep the checked-in example unchanged:

```bash
cd examples/07-compile-cache
workdir="$(mktemp -d)"
cp -R . "$workdir/"
cd "$workdir"

# Discover and load metadata without running the plugin or writing reports.
kompos configs compile build --dry-run

# Refresh inherited inputs, then write both consumers' reports.
kompos configs compile build --prune
cat generated/reports/alpha-after-plugin/report.yaml
cat generated/reports/beta-after-plugin/report.yaml

# Repeat: the report data and rewritten inputs remain identical.
kompos configs compile build --prune
```

The first report contains:

```yaml
consumer: alpha
config:
  project: cache-demo
  message: after-plugin
  replicas: 3
  feature_enabled: true
```

The second has the same config and `consumer: beta`. Integers, booleans and the
whole `report` mapping remain typed after interpolation.

## What happens

1. Compile preflight loads metadata for all three compositions. Both consumers
   initially inherit `before-plugin`, one replica and the disabled feature.
2. The configured `build_order` runs `external/refresh` before `manual/report`.
   The plugin receives only its two declared dotted input keys and returns YAML
   bodies and absolute destination paths. Kompos performs the writes.
3. `shared.yaml` is rewritten with the desired message and replica count.
   `generated_features.yaml` is added beside it, overriding the ancestor's
   disabled-feature default.
4. Both consumers generate reports and instance paths using the refreshed values
   during that same compile. Pruning also uses the updated instance names.
   The consumers' `composition.output_subdir` and the report composition property
   both select `reports`, keeping generation and pruning in the same directory.

Parsed YAML is shared across compositions for one compile invocation. Unresolved
merged hierarchies are cached per path; each use gets an independent copy before
output interpolation and dynamic or secret resolution. Existing-file changes
are detected through device/inode, size, modification-time and change-time
fingerprints. Hierarchy membership is rediscovered to detect new or removed YAML
files. There is no persisted cache, and a new invocation starts with a new cache.

The plugin applies fixed desired values rather than incrementing counters or
appending data. On repeated builds it rewrites the same YAML and reports;
`generated_features.yaml` and generated/runtime files are ignored by Git.

This is ordered execution, not a dependency DAG or rerun scheduler. Consumers
must run after their producer. Cache invalidation makes later reads fresh; it
does not rerun earlier compositions or discover new composition directories
created after the initial discovery pass. A compile dry-run lists compositions
without executing the plugin, so it does not preview post-mutation reports.
