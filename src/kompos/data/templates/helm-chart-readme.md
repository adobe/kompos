<!-- MANAGED BY KOMPOS — DO NOT EDIT MANUALLY -->
<!-- Re-generated on every kompos generate run -->

# Chart values: {chart_name}

Rendered Helm values for **{chart_name}**, consumed by ArgoCD from
`generated/clusters/{{cluster}}/helm-values/{chart_name}.yaml`.

Symlinks under `generated/` point at that output. Do not edit them — kompos
overwrites the source of truth on every `helm generate` run.

{pipeline_diagram}

## Where values come from

| Step | Source | Location |
|------|--------|----------|
| 1 | Kompos hierarchy | `configs/` — cluster, env, and chart registry enablement |
| 2 | Terraform outputs | `generated/clusters/{{cluster}}/terraform-outputs/tfe-outputs.yaml` |
| 3 | Bridge template | `{bridge_filename}` — `{{{{ }}}}` placeholders resolved per cluster |
| 4 | Cross-env defaults | `{overrides_subdir}/default.yaml` (optional) |
| 5 | Environment override | `{overrides_subdir}/{{env}}.yaml` (optional) |
| 6 | Cluster override | `{overrides_subdir}/{{cluster}}.yaml` (optional; wins conflicts) |

Steps 4–6 are plain YAML merged in order after the bridge is rendered.

### Override files in this chart

{override_files_list}

{chart_links_section}## Deployment inventory

Clusters where this chart is enabled and values are generated (grouped by environment).

{deployment_inventory}

## How to regenerate

```bash
kompos configs/.../cluster=.../composition=helm-values helm generate
```
