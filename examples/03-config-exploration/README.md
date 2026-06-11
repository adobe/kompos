# Example 03: Configuration Exploration

**Learn how to explore, trace, and compare hierarchical configurations using the `explore` runner**

---

## Overview

This example demonstrates the `explore` runner capabilities for exploring hierarchical configuration.

## Directory Structure

```
config/
├── defaults.yaml                    # Root level defaults
├── cloud=aws/
│   ├── aws.yaml                     # Cloud-specific config
│   └── env=dev/
│       ├── dev.yaml                 # Environment config
│       ├── cluster=cluster1/
│       │   └── cluster1.yaml        # Cluster-specific config
│       └── cluster=cluster2/
│           └── cluster2.yaml        # Another cluster
└── cloud=aws/
    └── env=prod/
        ├── prod.yaml
        └── cluster=prod1/
            └── prod1.yaml
```

## Sample Configurations

**defaults.yaml:**

```yaml
cloud:
  type: aws
  region: us-west-2

terraform:
  version: "1.5.0"

vpc:
  cidr_block: "10.0.0.0/16"

cluster:
  size: medium
  instance_type: t3.large
```

**cloud=aws/aws.yaml:**

```yaml
cloud:
  provider: aws
  
provider:
  aws:
    version: "~> 5.0"

vpc:
  enable_dns: true
  enable_nat: true
```

**env=dev/dev.yaml:**

```yaml
cluster:
  size: small               # Override for dev
  instance_type: t3.medium  # Override for dev

vpc:
  cidr_block: "10.1.0.0/16"  # Override for dev

terraform:
  version: "1.5.0"  # Latest for dev
```

**cluster=cluster1/cluster1.yaml:**

```yaml
cluster:
  name: cluster1
  
vpc:
  cidr_block: "10.1.1.0/24"  # Cluster-specific override
  
tags:
  team: platform
  environment: dev
```

## Running Explore Commands

### 1. Analyze Distribution

```bash
cd examples/explore
kompos config/cloud=aws/env=dev/cluster=cluster1 explore analyze
```

**Expected Output:**

```
================================================================================
HIERARCHICAL CONFIGURATION ANALYSIS
================================================================================
Config Path: config/cloud=aws/env=dev/cluster=cluster1
Total Layers: 4

Layer: config/
  New Variables: 6
    + cloud.type
    + cloud.region
    + terraform.version
    + vpc.cidr_block
    + cluster.size
    + cluster.instance_type
  Overridden Variables: 0
  Unchanged: 0

Layer: config/cloud=aws/
  New Variables: 4
    + cloud.provider
    + provider.aws.version
    + vpc.enable_dns
    + vpc.enable_nat
  Overridden Variables: 0
  Unchanged: 6

Layer: config/cloud=aws/env=dev/
  New Variables: 0
  Overridden Variables: 3
    ~ cluster.size (medium → small)
    ~ cluster.instance_type (t3.large → t3.medium)
    ~ vpc.cidr_block (10.0.0.0/16 → 10.1.0.0/16)
  Unchanged: 7

Layer: config/cloud=aws/env=dev/cluster=cluster1/
  New Variables: 4
    + cluster.name
    + tags.team
    + tags.environment
  Overridden Variables: 1
    ~ vpc.cidr_block (10.1.0.0/16 → 10.1.1.0/24)
  Unchanged: 9
```

### 2. Trace Specific Value

```bash
kompos config/cloud=aws/env=dev/cluster=cluster1 explore trace --key vpc.cidr_block
```

**Expected Output:**

```
================================================================================
VALUE TRACE: vpc.cidr_block
================================================================================
Config Path: config/cloud=aws/env=dev/cluster=cluster1

  config/
    Value: 10.0.0.0/16 [NEW]

  config/cloud=aws/
    Value: 10.0.0.0/16

  config/cloud=aws/env=dev/
    Value: 10.1.0.0/16 [OVERRIDE]

  config/cloud=aws/env=dev/cluster=cluster1/
    Value: 10.1.1.0/24 [OVERRIDE]
```

### 3. Visualize Hierarchy

```bash
kompos config/cloud=aws/env=dev explore visualize --format dot --output-file hierarchy.dot
dot -Tpng hierarchy.dot -o hierarchy.png
```

### 4. Compare Configurations

```bash
kompos config/cloud=aws/env=dev explore compare --keys vpc.cidr_block cluster.size cluster.instance_type
```

**Expected Output:**

```
================================================================================
CONFIGURATION COMPARISON MATRIX
================================================================================

Key: vpc.cidr_block
  config/cloud=aws/env=dev/cluster=cluster1: 10.1.1.0/24
  config/cloud=aws/env=dev/cluster=cluster2: 10.1.2.0/24

Key: cluster.size
  config/cloud=aws/env=dev/cluster=cluster1: small
  config/cloud=aws/env=dev/cluster=cluster2: small

Key: cluster.instance_type
  config/cloud=aws/env=dev/cluster=cluster1: t3.medium
  config/cloud=aws/env=dev/cluster=cluster2: t3.small
```

## Use Cases Demonstrated

1. **Debug Override Behavior**: See exactly where `vpc.cidr_block` gets overridden
2. **Understand Hierarchy**: Visualize how many variables exist at each level
3. **Compare Environments**: Spot differences between dev and prod configs
4. **Documentation**: Generate diagrams and reports for team onboarding

## Try It Yourself

1. Modify `cluster1.yaml` to override `cluster.size`
2. Run analyze to see the new override
3. Run trace on `cluster.size` to see the full path
4. Compare cluster1 vs cluster2 to see differences

