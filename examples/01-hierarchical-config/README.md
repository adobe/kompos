# Example 01: Hierarchical Configuration

**Learn how Kompos merges configuration files based on directory structure**

---

## Overview

This example demonstrates Kompos's hierarchical configuration system powered by [himl](https://github.com/adobe/himl).

**Key concept:** Configuration files are layered and merged based on the directory path you specify.

## How It Works

### Directory Structure

```
config/
└── cloud=aws/
    ├── aws.yaml                    # Cloud-level config
    └── env=dev/
        ├── dev.yaml                # Environment-level config
        └── cluster=cluster1/
            ├── conf.yaml           # Cluster-level config
            └── composition=terraform/
                ├── terraform=cluster/
                │   └── conf.yaml   # Composition-specific config
                └── terraform=network/
                    └── conf.yaml
```

### Configuration Merging

When you run:

```bash
kompos config/cloud=aws/env=dev/cluster=cluster1/composition=terraform/terraform=cluster ...
```

Kompos merges configs in order:

```
1. cloud=aws/aws.yaml
2. cloud=aws/env=dev/dev.yaml
3. cloud=aws/env=dev/cluster=cluster1/conf.yaml
4. cloud=aws/env=dev/cluster=cluster1/composition=terraform/terraform=cluster/conf.yaml
   ↓
Final merged configuration
```

### Example Merging

**`cloud=aws/aws.yaml`:**

```yaml
cloud:
  provider: aws
  region: us-east-1

defaults:
  instance_type: t3.medium
```

**`cloud=aws/env=dev/dev.yaml`:**

```yaml
environment: dev

defaults:
  instance_type: t3.small  # Override for dev
```

**`cloud=aws/env=dev/cluster=cluster1/conf.yaml`:**

```yaml
cluster:
  name: cluster1
  vpc_cidr: 10.0.0.0/16
```

**Merged Result:**

```yaml
cloud:
  provider: aws
  region: us-east-1
environment: dev
defaults:
  instance_type: t3.small  # Overridden by dev.yaml
cluster:
  name: cluster1
  vpc_cidr: 10.0.0.0/16
```

## Usage Examples

> Note: You need `.komposconfig.yaml` (already present in this folder) for this to work.

### 1. View merged configuration

```bash
# View the final merged config for a specific path
kompos config/env=dev/cluster=cluster1/composition=network config --format yaml
```

### 2. Run Terraform for all compositions

```bash
# Generates config and runs terraform plan for all compositions in cluster1
kompos config/env=dev/cluster=cluster1 terraform plan
```

### 3. Run Terraform for single composition

```bash
# Run only the network composition
kompos config/env=dev/cluster=cluster1/composition=network terraform apply --skip-plan
```

### 4. Compare different clusters

```bash
# View cluster1 config
kompos config/env=dev/cluster=cluster1 config --format yaml > cluster1.yaml

# View cluster2 config (notice the differences!)
kompos config/env=dev/cluster=cluster2 config --format yaml > cluster2.yaml

diff cluster1.yaml cluster2.yaml
```

## Benefits

- ✅ **DRY (Don't Repeat Yourself)**: Common values defined once at higher levels
- ✅ **Environment-specific overrides**: Dev can use smaller instances than prod
- ✅ **Clear precedence**: More specific (deeper) configs override general ones
- ✅ **Flexible structure**: Organize by cloud, environment, cluster, composition, etc.
- ✅ **Easy to maintain**: Change one file to affect multiple clusters/environments

## Learn More

- Full architecture documentation: [`/docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md)
- Himl documentation: https://github.com/adobe/himl
