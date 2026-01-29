# Example 02: Module Version Pinning

**Learn how to pin Terraform module versions per environment using `.tf.versioned` files**

---

> **For complete Kompos architecture and file generation documentation,
see [`/docs/ARCHITECTURE.md`](../../../docs/ARCHITECTURE.md)**

## Quick Start

This example demonstrates Terraform module version pinning per environment.

### Run It

```bash
# Dev cluster (uses v2.0.0-rc)
cd examples/features/02-module-version-pinning
kompos config/env=dev/cluster=cluster1/composition=terraform terraform plan --dry-run
```

### What This Demonstrates

**Template** (`compositions/terraform/aws/vpc/main.tf.versioned`):

```hcl
module "vpc" {
  source = "git::https://...?ref={{vpc.module_version}}"
}
```

**Config** (`config/.../cluster.yaml`):

```yaml
vpc:
  module_version: "v2.0.0-rc"  # Different per environment
```

**Generated** (`.kompos-runtime/.../main.tf`):

```hcl
module "vpc" {
  source = "git::https://...?ref=v2.0.0-rc"
}
```

## Files

```
examples/features/02-module-version-pinning/
├── config/                      # Hierarchical configuration
│   ├── default.yaml
│   └── env=dev/
│       └── cluster=cluster1/
│           └── ...
├── compositions/terraform/aws/vpc/
│   ├── main.tf.versioned        # Template
│   ├── variables.tf
│   └── outputs.tf
└── .komposconfig.yaml
```

See [`/docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md) for full documentation.
