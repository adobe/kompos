# Example 04: TFE Multi-Cluster Management

**Learn how to manage multiple Terraform Enterprise (TFE) clusters with different configurations and module versions**

---

## Overview

This example demonstrates Kompos's powerful per-cluster composition generation for Terraform Enterprise (TFE),
featuring:

- **Per-cluster provider configuration from Hiera** (region, role_arn, etc.)
- **Module version pinning per cluster** via `.tf.versioned` files
- **Hierarchical configuration inheritance** across environments
- **Generated TFE workspaces** with all necessary files

## Overview

This example shows how to manage multiple EKS clusters across different environments and regions with:

- Different module versions per environment (dev uses latest, prod uses tested stable)
- Per-cluster provider configs (different regions, IAM roles)
- Single source composition, multiple generated working directories

## Directory Structure

```
04-tfe-multi-cluster/
├── .komposconfig.yaml                    # Kompos configuration
├── compositions/
│   └── terraform/
│       └── aws/
│           └── cluster/
│               ├── main.tf.versioned     # Module sources with {{version}} placeholders
│               ├── variables.tf          # Standard Terraform variables
│               └── outputs.tf            # Standard Terraform outputs
└── data/                                 # Hierarchical configuration
    ├── default.yaml                      # Global defaults
    └── cloud=aws/
        ├── cloud.yaml                    # AWS-specific config
        └── project=demo/
            ├── project.yaml
            ├── env=dev/
            │   ├── env.yaml             # Dev environment (latest versions)
            │   └── region=us-west-2/
            │       ├── region.yaml
            │       └── cluster=demo-cluster-01/
            │           └── cluster.yaml  # Cluster-specific config
            └── env=prod/
                ├── env.yaml             # Prod environment (stable versions)
                └── region=us-east-1/
                    ├── region.yaml
                    └── cluster=demo-cluster-02/
                        └── cluster.yaml
```

## Key Features Demonstrated

### 1. Module Version Pinning

**Source: `main.tf.versioned`**

```hcl
module "vpc" {
  source = "git::https://github.com/terraform-aws-modules/terraform-aws-vpc.git?ref={{vpc.module_version}}"
  # ...
}

module "eks" {
  source = "git::https://github.com/terraform-aws-modules/terraform-aws-eks.git?ref={{eks.module_version}}"
  # ...
}
```

**Hiera Dev: `env=dev/env.yaml`**

```yaml
vpc:
  module_version: v5.1.2    # Latest stable for dev

eks:
  module_version: v19.16.0  # Latest stable for dev
```

**Hiera Prod: `env=prod/env.yaml`**

```yaml
vpc:
  module_version: v5.1.0    # Tested stable for prod

eks:
  module_version: v19.15.0  # Tested stable for prod
```

### 2. Provider Configuration from Hiera

**Hiera: `default.yaml`**

```yaml
provider:
  aws:
    region: "{{region.location}}"
    assume_role:
      role_arn: "{{account.role_arn}}"
```

**Generated: `provider.tf.json` (dev cluster)**

```json
{
  "provider": {
    "aws": {
      "region": "us-west-2",
      "assume_role": {
        "role_arn": "arn:aws:iam::111122223333:role/TerraformExecutionRole"
      }
    }
  }
}
```

### 3. Hierarchical Configuration Inheritance

Values are inherited and can be overridden at each level:

```
default.yaml             → Global defaults (all clusters)
  └─ cloud=aws/cloud.yaml      → AWS-specific
      └─ env=dev/env.yaml      → Dev environment (latest versions)
          └─ region=us-west-2/  → Region-specific (AZs)
              └─ cluster=demo-cluster-01/  → Cluster-specific (VPC, EKS settings)
```

## Usage

### 1. Explore Configuration for a Cluster

```bash
# See final resolved config for dev cluster
kompos data/cloud=aws/project=demo/env=dev/region=us-west-2/cluster=demo-cluster-01/composition=terraform config --format yaml

# Trace where values come from
kompos data/cloud=aws/.../cluster=demo-cluster-01/... explore trace vpc.module_version
```

### 2. Generate TFE Resources

```bash
# Generate everything for dev cluster (tfvars + workspace + composition)
kompos data/cloud=aws/project=demo/env=dev/region=us-west-2/cluster=demo-cluster-01/composition=terraform tfe generate

# Generate everything for prod cluster
kompos data/cloud=aws/project=demo/env=prod/region=us-east-1/cluster=demo-cluster-02/composition=terraform tfe generate
```

### 3. Check Generated Files

After running `tfe generate`, you'll have:

```
generated/
├── clusters/
│   ├── demo-dev-usw2-cluster-01/
│   │   └── demo-dev-usw2-cluster-01.tfvars.yaml     # Terraform variables
│   └── demo-prod-use1-cluster-02/
│       └── demo-prod-use1-cluster-02.tfvars.yaml
├── workspaces/
│   ├── demo-dev-usw2-cluster-01.workspace.yaml      # TFE workspace config
│   └── demo-prod-use1-cluster-02.workspace.yaml
└── compositions/
    ├── demo-dev-usw2-cluster-01/                    # Per-cluster working_directory
    │   ├── provider.tf.json                         # Generated from hiera (us-west-2)
    │   ├── main.tf                                  # Generated from .versioned (latest versions)
    │   ├── variables.tf                             # Copied
    │   └── outputs.tf                               # Copied
    └── demo-prod-use1-cluster-02/                   # Per-cluster working_directory
        ├── provider.tf.json                         # Generated from hiera (us-east-1)
        ├── main.tf                                  # Generated from .versioned (stable versions)
        ├── variables.tf                             # Copied
        └── outputs.tf                               # Copied
```

### 4. Compare Configurations Across Clusters

```bash
# Compare module versions between dev and prod
kompos data/.../cluster=demo-cluster-01/... explore compare \
  data/.../cluster=demo-cluster-02/... \
  --keys vpc.module_version eks.module_version

# Visualize hierarchy for a cluster
kompos data/.../cluster=demo-cluster-01/... explore visualize \
  --format dot --output cluster-01-hierarchy.dot
```

## What Gets Generated

### For Each Cluster

All files are generated in a single cluster directory: `generated/clusters/<cluster-name>/`

1. **Composition Files** (Terraform working directory):
    - `main.tf` - Modules with resolved version tags from hiera
    - `provider.tf` - Static provider config (uses native TF variables)
    - `variables.tf`, `outputs.tf` - Static files copied as-is

2. **Tfvars File** (`generated.tfvars.yaml`):
    - All configuration values for Terraform variables
    - Includes provider variables (aws_region, role_arn, etc.)
    - Excludes system metadata (workspaces, composition keys)

3. **Workspace Config** (`generated/workspaces/<cluster-name>.workspace.yaml`):
    - TFE workspace settings
    - Terraform version, auto-apply settings
    - Environment variables pointing to tfvars file
    - Tags for organization

## Key Differences: Dev vs Prod

| Aspect          | Dev (demo-cluster-01) | Prod (demo-cluster-02) |
|-----------------|-----------------------|------------------------|
| **Region**      | us-west-2             | us-east-1              |
| **VPC Module**  | v5.1.2 (latest)       | v5.1.0 (stable)        |
| **EKS Module**  | v19.16.0 (latest)     | v19.15.0 (stable)      |
| **K8s Version** | 1.28                  | 1.27                   |
| **NAT Gateway** | Single (cost savings) | Multi-AZ (HA)          |
| **Endpoint**    | Public + Private      | Private only           |
| **Node Groups** | 1 (on-demand)         | 2 (on-demand + spot)   |
| **Min Nodes**   | 1                     | 3                      |

## Module Version Strategy

### Development Environment

- **Goal**: Test latest stable versions
- **Risk Tolerance**: Medium (can tolerate issues)
- **Update Frequency**: Weekly/as needed
- **Versions**: Latest stable releases

### Production Environment

- **Goal**: Stability and reliability
- **Risk Tolerance**: Low (avoid breaking changes)
- **Update Frequency**: After testing in dev
- **Versions**: Tested stable releases (usually 1-2 versions behind latest)

### Workflow

1. Update module versions in `env=dev/env.yaml`
2. Test in development clusters
3. After validation, promote versions to `env=prod/env.yaml`
4. All changes tracked in git history

## Benefits of This Approach

### 1. DRY (Don't Repeat Yourself)

- One source composition (`main.tf.versioned`)
- N clusters with different configs
- No code duplication

### 2. Version Control

- Module versions in version-controlled YAML
- Easy to track what versions are running where
- Audit trail for version changes

### 3. Environment Isolation

- Dev can use cutting-edge versions
- Prod uses battle-tested versions
- Same source code, different runtime

### 4. Per-Cluster Customization

- Different regions (compliance, latency)
- Different IAM roles (security boundaries)
- Different sizing (cost optimization)

### 5. TFE Integration

- Generated working directories ready for TFE
- Workspace configs with all settings
- Variables properly scoped

## Configuration Reference

### `.komposconfig.yaml` Settings

```yaml
tfe:
  himl_name_key: "cluster.fullName"      # How to name outputs
  use_cluster_subdir: true               # Separate directories per cluster
  generate_compositions: true            # Enable composition generation
  compositions_dir: "./generated/clusters"  # Consolidated with clusters_dir
  clusters_dir: "./generated/clusters"
  workspaces_dir: "./generated/workspaces"
  tfvars_format: "yaml"                  # or "json"
  tfvars_filename: "generated"           # Optional: base filename (omit to use cluster name)
  workspace_format: "yaml"               # or "json"
```

### Required Hiera Keys

For composition generation to work, your hierarchy must provide:

- `cluster.fullName` - Unique cluster identifier
- `region.location` - AWS region
- `account.role_arn` - IAM role for Terraform
- `provider.*` - Provider configuration block
- `<module>.module_version` - For each module in `.tf.versioned`

## Troubleshooting

### Missing Module Version

```
Error: Config key "vpc.module_version" not found for interpolation.
```

**Solution**: Add the key to your hierarchy (typically in `env.yaml` or `cluster.yaml`).

### Wrong Region in Provider

Check the hierarchy for `region.location`:

```bash
kompos data/.../cluster=demo-cluster-01/... explore trace region.location
```

### Composition Not Generated

1. Check `.komposconfig.yaml`: `generate_compositions: true`
2. Check source composition exists: `compositions/terraform/aws/cluster/`
3. Check for errors in the output

## Next Steps

1. **Customize** the example for your infrastructure
2. **Add more modules** to `main.tf.versioned` (RDS, ALB, etc.)
3. **Create more clusters** in different environments/regions
4. **Integrate with TFE** using the generated workspace configs
5. **Automate** generation in your CI/CD pipeline

## See Also

- [Example 03: Config Exploration](../03-config-exploration/README.md) - For analyzing and tracing configurations
- [Example 02: Module Version Pinning](../02-module-version-pinning/README.md) - Simpler version pinning example
- [Example 01: Hierarchical Config](../01-hierarchical-config/README.md) - Deep dive into hierarchy
- [Kompos Documentation](../../../docs/) - Complete documentation

