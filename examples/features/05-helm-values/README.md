# Example 05: Helm Values Rendering

**Learn how to render cluster-specific Helm values using kompos hierarchy data and TFE outputs**

---

## Overview

This example demonstrates the `helm generate` runner, which:

- Reads `helm.charts.*` from the kompos hierarchy to know which charts are enabled
- Scans a `values/` directory to discover chart templates (`values.yaml` with `{{}}` placeholders)
- Builds an interpolation context from the hierarchy + TFE runtime outputs
- Renders each enabled chart's `values.yaml` and writes clean output to `generated/clusters/{cluster}/argoapps/`

**Key concepts:**
- `{{cluster.*}}` — resolved from the kompos config hierarchy
- `{{global.infra.*}}` — resolved from TFE outputs (`generated/clusters/{cluster}/outputs/tfe-outputs.yaml`)
- Static values pass through unchanged — the renderer is transparent
- `argoapps/` is owned by `helm generate` — stale files are pruned automatically

---

## Directory Structure

```
05-helm-values/
├── .komposconfig.yaml                          # Kompos configuration (enclosing key, output paths)
├── data/                                       # Hierarchical configuration
│   └── cloud=aws/
│       ├── defaults_helm.yaml                  # ALL charts: enabled/disabled + default versions
│       └── project=demo/
│           └── env=dev/
│               └── region=us-west-2/
│                   ├── region.yaml             # region.* + env.*
│                   └── cluster=demo-cluster-01/
│                       ├── cluster.yaml        # cluster.name + cluster.fullName
│                       └── composition=helm-values/
│                           └── helm.yaml       # composition.instance + cluster overrides
├── generated/
│   └── clusters/
│       └── demo-dev-usw2-cluster-01/
│           ├── outputs/
│           │   └── tfe-outputs.yaml            # Mock TFE runtime outputs (global.infra.*)
│           └── argoapps/                       # Output: rendered helm values (generated)
│               ├── my-ingress.yaml
│               └── my-app.yaml
└── values/                                     # Chart values.yaml templates (from apps repo)
    ├── my-ingress/
    │   └── values.yaml                         # Uses {{global.infra.adobe_security_group_ids.*}}
    ├── my-app/
    │   └── values.yaml                         # Uses {{cluster.fullName}}, {{env.name}}, pod identity ARN
    └── my-worker/
        └── values.yaml                         # Disabled by default in defaults_helm.yaml
```

---

## Chart Registry

Defined in `data/cloud=aws/defaults_helm.yaml` — applies to all clusters:

```yaml
helm:
  charts:
    my-ingress:
      enabled: true
      version: "1.2.0"
    my-app:
      enabled: true
      version: "2.0.0"    # overridden to 2.1.0 for demo-cluster-01
    my-worker:
      enabled: false       # opt-in per cluster
      version: "1.0.0"
```

The cluster at `composition=helm-values/helm.yaml` pins `my-app` to `2.1.0` and inherits everything else.

---

## Running the Example

```bash
cd examples/features/05-helm-values

# List enabled charts for the demo cluster
kompos data/cloud=aws/project=demo/env=dev/region=us-west-2/cluster=demo-cluster-01/composition=helm-values \
    helm list

# Dry-run: render all enabled charts, print to stdout
kompos data/cloud=aws/project=demo/env=dev/region=us-west-2/cluster=demo-cluster-01/composition=helm-values \
    helm generate \
    --charts-dir ./values \
    --dry-run

# Generate: write rendered values to generated/clusters/{cluster}/argoapps/
kompos data/cloud=aws/project=demo/env=dev/region=us-west-2/cluster=demo-cluster-01/composition=helm-values \
    helm generate \
    --charts-dir ./values

# Single chart (local dev iteration)
kompos data/cloud=aws/project=demo/env=dev/region=us-west-2/cluster=demo-cluster-01/composition=helm-values \
    helm generate \
    --chart-dir ./values/my-app \
    --dry-run
```

---

## Expected Output

### `helm list`

```
Enabled charts for cluster: demo-dev-usw2-cluster-01

  CHART                                         VERSION      STATUS
  ───────────────────────────────────────────── ──────────── ──────
  my-app                                        2.1.0        enabled
  my-ingress                                    1.2.0        enabled

  Disabled:
    my-worker

  Untracked:
    (none)
```

### `helm generate --dry-run`

```yaml
# ── my-app ──────────────────────────────────────
my-app:
  namespace: my-app
  replicaCount: 2
  image:
    repository: my-org/my-app
    pullPolicy: IfNotPresent
  global:
    clusterName: demo-dev-usw2-cluster-01    # resolved from {{cluster.fullName}}
    environment: dev                          # resolved from {{env.name}}
    region: us-west-2                         # resolved from {{region.location}}
  serviceAccount:
    annotations:
      eks.amazonaws.com/role-arn: arn:aws:iam::111122223333:role/demo-dev-usw2-cluster-01-my-app-pod-identity

# ── my-ingress ──────────────────────────────────────
my-ingress:
  namespace: ingress
  affinity: ...                               # static — unchanged
  service:
    annotations:
      securityGroups: sg-0aaa111222333444,sg-0bbb555666777888,sg-0ssh999000111222
```

---

## Key Design Points

### Interpolation context

```
context = {
  cluster:  { name: demo-cluster-01, fullName: demo-dev-usw2-cluster-01 }
  env:      { name: dev, type: non-prod }
  region:   { name: us-west-2, location: us-west-2 }
  helm:     { charts: { my-ingress: {...}, my-app: {...}, my-worker: {...} } }
  global:   { infra: { cluster_name: ..., vpc_id: ..., adobe_security_group_ids: {...} } }
  # + all other kompos hierarchy keys
}
```

### Internal enclosing key (`__helm_values__`)

The renderer injects each chart's `values.yaml` under `__helm_values__` in the context dict,
runs `InterpolationResolver` on the entire context (so `{{}}` in the values can reference any
context key), then extracts `__helm_values__` as clean output. The context data never appears
in the output.

### Pruning

After rendering, `argoapps/` is pruned — any `.yaml` file not in the current rendered set is
removed. This ensures ArgoCD never applies values from a disabled or removed chart.

---

## What to Try

1. **Disable a chart** — set `my-ingress.enabled: false` in `helm.yaml` and re-run `helm generate`. Check that `argoapps/my-ingress.yaml` is pruned.

2. **Add an untracked chart** — add a `values/my-new-chart/values.yaml` file. Run `helm list` to see it in the "Untracked" section.

3. **Override a version** — change `my-app.version` in `helm.yaml` to a different value. Run `helm list` to confirm the override.

4. **Add interpolation** — add `{{global.infra.vpc_id}}` to one of the `values.yaml` templates and see it resolved in the dry-run output.
