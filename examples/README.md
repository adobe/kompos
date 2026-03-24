# Kompos Examples

Learn Kompos through progressive, hands-on examples. Each example builds on concepts from the previous ones.

## Learning Path

### 1. [Hierarchical Configuration](features/01-hierarchical-config/)

**Learn:** How Kompos merges configuration files based on directory structure

- **Difficulty:** Beginner · **Time:** 5-10 min
- **Topics:** Configuration hierarchy, merging, overrides

```bash
cd examples/features/01-hierarchical-config
kompos config/cloud=aws/env=dev/cluster=cluster1/composition=terraform/terraform=cluster config
```

---

### 2. [Module Version Pinning](features/02-module-version-pinning/)

**Learn:** How to pin Terraform module versions per environment

- **Difficulty:** Beginner · **Time:** 10-15 min
- **Topics:** `.tf.versioned` files, `{{}}` interpolation, version management

```bash
cd examples/features/02-module-version-pinning
kompos config/env=dev/... terraform plan --dry-run
```

---

### 3. [Configuration Exploration](features/03-config-exploration/)

**Learn:** Trace, compare, and visualize hierarchical configurations

- **Difficulty:** Intermediate · **Time:** 15-20 min
- **Topics:** `explore` runner, tracing values, comparing configs

```bash
cd examples/features/03-config-exploration
kompos config/... explore trace --key vpc.cidr_block
kompos config/... explore compare --keys vpc.cidr_block
```

---

### 4. [TFE Multi-Cluster](features/04-tfe-multi-cluster/)

**Learn:** Generate per-cluster TFE workspaces with different module versions

- **Difficulty:** Advanced · **Time:** 30-45 min
- **Topics:** TFE integration, per-cluster compositions, multi-environment strategy

```bash
cd examples/features/04-tfe-multi-cluster

# Generate tfvars + workspace for dev cluster
kompos data/cloud=aws/project=demo/env=dev/region=us-west-2/cluster=demo-cluster-01/composition=terraform \
    tfe generate

# Generate for prod cluster (different versions from hierarchy)
kompos data/cloud=aws/project=demo/env=prod/region=us-east-1/cluster=demo-cluster-02/composition=terraform \
    tfe generate
```

---

### 5. [Helm Values Rendering](features/05-helm-values/)

**Learn:** Render cluster-specific Helm values from hierarchy data and TFE outputs

- **Difficulty:** Intermediate · **Time:** 15-20 min
- **Topics:** `helm` runner, `{{}}` interpolation, TFE outputs, ArgoCD delivery

**Key Concept:** A `values.yaml` with `{{cluster.*}}` and `{{global.infra.*}}` placeholders is rendered
per-cluster using kompos hierarchy data and Terraform outputs. The output feeds directly into ArgoCD
via the `$clusterValues` ref source.

```bash
cd examples/features/05-helm-values

# List enabled charts for the demo cluster
kompos data/cloud=aws/project=demo/env=dev/region=us-west-2/cluster=demo-cluster-01/composition=helm-values \
    helm list

# Dry-run: render all enabled charts, print to stdout
kompos data/cloud=aws/project=demo/env=dev/region=us-west-2/cluster=demo-cluster-01/composition=helm-values \
    helm generate --dry-run

# Generate: write rendered values to generated/clusters/{cluster}/argoapps/
kompos data/cloud=aws/project=demo/env=dev/region=us-west-2/cluster=demo-cluster-01/composition=helm-values \
    helm generate
```

---

## Example Comparison

| Example                       | Runner  | Focus                    | Difficulty | Time      |
|-------------------------------|---------|--------------------------|------------|-----------|
| **01-hierarchical-config**    | config  | Config basics            | ⭐ Low      | 5-10 min  |
| **02-module-version-pinning** | tfe     | Versioning               | ⭐⭐ Medium  | 10-15 min |
| **03-config-exploration**     | explore | Debugging                | ⭐⭐ Medium  | 15-20 min |
| **04-tfe-multi-cluster**      | tfe     | Terraform / TFE workflow | ⭐⭐⭐ High   | 30-45 min |
| **05-helm-values**            | helm    | Helm / ArgoCD delivery   | ⭐⭐ Medium  | 15-20 min |

---

## Prerequisites

- Kompos installed (`pip install kompos` or from source)
- For examples 2 and 4: Terraform installed
- Basic YAML familiarity

---

## File Structure

```
examples/
├── README.md
└── features/
    ├── 01-hierarchical-config/
    ├── 02-module-version-pinning/
    ├── 03-config-exploration/
    ├── 04-tfe-multi-cluster/     ← TFE + Terraform workflow
    └── 05-helm-values/           ← Helm values + ArgoCD delivery
```
