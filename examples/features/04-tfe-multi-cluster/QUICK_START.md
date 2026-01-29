# Quick Reference: TFE Per-Cluster Composition

## One-Line Summary

Generate per-cluster Terraform working directories with provider configs and module versions from Hiera.

## Quick Start

```bash
# 1. Navigate to example
cd examples/features/tfe-per-cluster

# 2. Generate dev cluster
kompos data/cloud=aws/project=demo/env=dev/region=us-west-2/cluster=demo-cluster-01/composition=terraform tfe generate

# 3. Check generated files
ls -R generated/
```

## Generated Output Structure

```
generated/
├── compositions/demo-dev-usw2-cluster-01/   ← TFE working_directory
│   ├── provider.tf.json                     ← Generated from hiera
│   ├── main.tf                              ← Resolved from .tf.versioned
│   ├── variables.tf                         ← Copied
│   └── outputs.tf                           ← Copied
├── clusters/demo-dev-usw2-cluster-01/
│   └── demo-dev-usw2-cluster-01.tfvars.yaml ← Terraform variables
└── workspaces/
    └── demo-dev-usw2-cluster-01.workspace.yaml ← TFE workspace config
```

## Key Concepts

### 1. Module Version Pinning

**Template** (`.tf.versioned`):

```hcl
source = "git::https://github.com/org/module.git?ref={{vpc.module_version}}"
```

**Hiera**:

```yaml
vpc:
  module_version: v5.1.2
```

**Generated** (`.tf`):

```hcl
source = "git::https://github.com/org/module.git?ref=v5.1.2"
```

### 2. Provider from Hiera

**Hiera**:

```yaml
region:
  location: us-west-2

provider:
  aws:
    region: "{{region.location}}"
```

**Generated** (`provider.tf.json`):

```json
{
  "provider": {
    "aws": {
      "region": "us-west-2"
    }
  }
}
```

## Common Commands

```bash
# View final config
kompos data/.../cluster=demo-cluster-01/... config --format yaml

# Trace value origin
kompos data/.../cluster=demo-cluster-01/... explore trace vpc.module_version

# Compare clusters
kompos data/.../cluster=demo-cluster-01/... explore compare \
  data/.../cluster=demo-cluster-02/... \
  --keys vpc.module_version eks.module_version

# Generate only tfvars
kompos data/.../cluster=demo-cluster-01/... tfe generate --workspace-only

# Generate only compositions
kompos data/.../cluster=demo-cluster-01/... tfe generate --tfvars-only
```

## Configuration Toggle

Enable/disable composition generation in `.komposconfig.yaml`:

```yaml
tfe:
  generate_compositions: true   # Set to false to skip composition generation
  compositions_dir: "./generated/clusters"  # Consolidated with clusters_dir
  clusters_dir: "./generated/clusters"
  tfvars_filename: "generated"  # Optional: simplified filename
```

## What Makes This Different

| Feature              | Before                   | With This Feature      |
|----------------------|--------------------------|------------------------|
| **Provider Config**  | Hardcoded in composition | From Hiera per cluster |
| **Module Versions**  | Hardcoded or tfvars      | From Hiera per cluster |
| **Per-Cluster Code** | Duplicate compositions   | One source, N outputs  |
| **Version Control**  | In .tf files             | In YAML hierarchy      |
| **Environment Diff** | Hard to compare          | Easy with explore      |

## Files Explained

| File                | Purpose                               | Source               |
|---------------------|---------------------------------------|----------------------|
| `main.tf.versioned` | Module template with {{placeholders}} | Composition source   |
| `main.tf`           | Resolved modules with actual versions | Generated            |
| `provider.tf.json`  | Provider config (region, role)        | Generated from hiera |
| `variables.tf`      | Terraform variable declarations       | Copied from source   |
| `outputs.tf`        | Terraform outputs                     | Copied from source   |
| `*.tfvars.yaml`     | Terraform variable values             | Generated from hiera |
| `*.workspace.yaml`  | TFE workspace settings                | Generated from hiera |

## Hierarchy Example

```
default.yaml (vpc.module_version: v5.1.0)
  └─ env=dev/env.yaml (vpc.module_version: v5.1.2)  ← Overrides default
      └─ cluster=demo-cluster-01/cluster.yaml
```

Result: `demo-cluster-01` uses `v5.1.2`

## Troubleshooting

**Q: Composition not generated?**

- Check: `.komposconfig.yaml` has `generate_compositions: true`
- Check: Source composition exists at `compositions/terraform/aws/cluster/`

**Q: Missing module version error?**

- Add `<module>.module_version` to your hierarchy (in `env.yaml` or `cluster.yaml`)

**Q: Wrong provider config?**

- Trace the values: `kompos ... explore trace region.location`

## Real-World Use Case

You have:

- 10 EKS clusters across dev/staging/prod
- Different AWS regions for each
- Different module versions (dev = latest, prod = stable)

With this feature:

- ✅ One source composition
- ✅ Module versions in YAML (version controlled)
- ✅ Generate 10 working directories automatically
- ✅ Each with correct provider (region/role)
- ✅ Each with correct module versions
- ✅ Ready to commit to git for TFE

## Integration with TFE

1. Generate compositions: `kompos ... tfe generate`
2. Commit `generated/` to your TFE-connected git repo
3. TFE workspaces use `working_directory: demo-dev-usw2-cluster-01/`
4. Each workspace gets its own isolated composition
5. Provider and module versions managed via Hiera

## Performance

- **Generation time**: ~1-2 seconds per cluster
- **Parallel generation**: Run multiple kompos commands in parallel
- **CI/CD friendly**: Deterministic output, idempotent

## Learn More

- Full README: [README.md](README.md)
- Explore docs: [../../docs/EXPLORE_RUNNER.md](../../../docs/EXPLORE_RUNNER.md)
- TFE docs: [../../docs/TFE_RUNNER.md](../../../docs/TFE_RUNNER.md)

