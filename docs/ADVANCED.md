# Advanced Guide

Deep dives into Kompos architecture, runners, and troubleshooting.

## Architecture

### Output Path Structure

Three-part hierarchy: `base/type/instance`

```
./generated/clusters/my-cluster-us-east-1/
 └─base─┘ └─type──┘ └──instance──────────┘
```

**Configuration:**
```yaml
# .komposconfig.yaml (parts 1 & 2)
komposconfig:
  defaults:
    base_dir: "./generated"  # Part 1
  compositions:
    properties:
      cluster:
        output_subdir: "clusters"  # Part 2

# Layered config (part 3)
composition:
  instance: "{{cluster.fullName}}"  # Part 3
```

### KomposConfig vs GenericRunner

**KomposConfig** - How Kompos operates
- Source: `.komposconfig.yaml`
- Controls: base dirs, execution order, exclusions
- Methods: `get_*_config()`, `*_path()`

**GenericRunner** - What you're deploying  
- Source: Layered configs (Himl)
- Contains: Cluster names, resource configs
- Methods: `get_composition_*()`

**Key Principle:** `.komposconfig.yaml` = tool settings, layered configs = infrastructure data

### Himl Integration

Kompos uses [himl](https://github.com/adobe/himl) for:
- Hierarchical YAML merging
- Interpolation resolution
- Value tracing
- Config generation

**Merge behavior:**
- Dicts: Deep merge
- Lists: Replace entirely
- Scalars: Override

## TFE Runner

### Generation Flow

```
1. Read layered configs → Himl merge
2. Resolve interpolations → {{key}} to values  
3. Process .tf.versioned → Inject module versions
4. Generate tfvars → Filter/exclude keys
5. Generate workspace config → TFE metadata
6. Copy composition files → main.tf, variables.tf
```

### Workspace Configuration

```yaml
# configs/.../defaults_terraform.yaml
workspaces:
  name: "{{composition.instance}}"
  role_arn: "arn:aws:iam::123456789012:role/TFE"
  project_id: "prj-abc123"
  working_directory: "generated/clusters/{{composition.instance}}/"
  tags:
    - "env:{{env.name}}"
    - "region:{{region.name}}"
  
terraform_version: "1.6.0"
```

**Generated file:** `workspaces/my-cluster.workspace.yaml`

### Module Versioning

**Template:** `main.tf.versioned`
```hcl
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "{{vpc.module_version}}"  # ← Placeholder
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "{{eks.module_version}}"
}
```

**Config:** Different versions per environment
```yaml
# env=prod/env.yaml
vpc:
  module_version: "5.1.0"
eks:
  module_version: "19.15.0"

# env=dev/env.yaml  
vpc:
  module_version: "5.2.0"
eks:
  module_version: "19.16.0"
```

**Result:** `generated/clusters/my-cluster/main.tf` (static file with resolved versions)

### Exclusions and Filters

**System Keys** - Kompos internal, always excluded:
```yaml
# .komposconfig.yaml
komposconfig:
  compositions:
    system_keys:
      tfe: [workspaces, composition, tfe, provider, terraform]
```

**Config Keys** - Composition-specific exclusions:
```yaml
komposconfig:
  compositions:
    config_keys:
      excluded:
        account: [cluster, vpc]  # Account doesn't need cluster config
        vpc: [cluster]           # VPC doesn't need cluster config
```

**Filters** - Include only specific keys:
```bash
kompos configs/... config --filter vpc --filter network
```

## Explore Runner

### Trace Command

Shows value evolution through hierarchy:

```bash
kompos configs/.../cluster=web explore trace vpc.cidr
```

**Output:**
```
VALUE TRACE: vpc.cidr
════════════════════════════════════════
Config Path: configs/.../cluster=web

  configs
    Value: None [UNDEFINED]
    
  cloud=aws
    Value: 10.0.0.0/16 [NEW]
    Source: cloud=aws/defaults.yaml:12
    
  env=prod
    Value: 10.0.0.0/16 [UNCHANGED]
    
  region=us-east-1
    Value: 10.1.0.0/16 [CHANGED]
    Source: region=us-east-1/region.yaml:8
    
  cluster=web
    Value: 10.1.0.0/16 [UNCHANGED]
```

### Compare Command

Diff configs between paths:

```bash
kompos configs/.../cluster=web explore compare \
  configs/.../cluster=api \
  --keys vpc.cidr,cluster.instance_type
```

**Output:**
```
COMPARISON RESULTS
════════════════════════════════════════
Key: vpc.cidr
  cluster=web: 10.1.0.0/16
  cluster=api: 10.2.0.0/16
  
Key: cluster.instance_type
  cluster=web: t3.large
  cluster=api: t3.medium
```

### Visualize Command

Shows hierarchy structure:

```bash
kompos configs/.../cluster=web explore visualize
```

### Analyze Command

Shows which files contribute keys:

```bash
kompos configs/.../cluster=web explore analyze
```

## Validation

### Validate Runner

Proactive configuration checks:

```bash
kompos configs/... validate
```

**Checks:**
- Excluded but referenced keys
- Unresolved interpolations
- Schema violations
- Missing required keys

### Excluded-But-Referenced

Detects when excluded keys are still used:

```yaml
# .komposconfig.yaml
komposconfig:
  compositions:
    config_keys:
      excluded:
        account: [cluster]  # cluster excluded for account
```

```yaml
# configs/.../composition=account/tags.yaml
tags:
  Cluster: "{{cluster.name}}"  # ← ERROR: cluster is excluded!
```

**Validation output:**
```
ERROR: excluded-but-referenced

Key: cluster
Composition: account
Excluded keys: [cluster, vpc]
Referenced in:
  - configs/.../composition=account/tags.yaml:3
  
Fix: Remove cluster references or update exclusions
```

## Debugging

### Auto-Debug

When interpolation fails, Kompos auto-analyzes:

```
ERROR: Interpolation could not be resolved {{cluster.name}}

AUTO-DEBUG ANALYSIS
════════════════════════════════════════
Key Path: cluster.name
Config: configs/.../composition=account

VALUE TRACE:
  cloud=aws: default [UNCHANGED]
  composition=account: default [UNCHANGED]

ROOT CAUSE: Key exists but is excluded
────────────────────────────────────────
'cluster' has a value but is excluded for composition 'account'

Excluded keys: cluster, vpc, node_groups

FIX OPTIONS:
1. Remove {{cluster.name}} references
2. Update .komposconfig.yaml exclusions
```

### Manual Debug

```bash
# Check raw config (no exclusions)
kompos configs/... config --skip-interpolation-validation

# Trace specific key
kompos configs/... explore trace key.path

# Debug interpolation
kompos configs/... explore debug --interpolation "{{key.path}}"

# View excluded keys
grep -A 5 "excluded:" .komposconfig.yaml
```

### Common Issues

**Issue: Unresolved interpolation**
```bash
# Check if key exists
kompos configs/... explore trace key.path

# Check if excluded
grep "excluded:" .komposconfig.yaml
```

**Issue: Wrong value**
```bash
# See where it's set
kompos configs/... explore trace key.path

# Compare with other config
kompos configs/.../a explore compare configs/.../b --keys key.path
```

**Issue: Dict not merging**
```yaml
# BAD: String interpolation doesn't merge
tags: "{{base_tags}}"

# GOOD: Use YAML merge keys
tags:
  <<: *base_tags
  Additional: value
```

**Issue: List not as expected**
```yaml
# Lists replace, don't merge
# Parent: [a, b]
# Child: [c]
# Result: [c] NOT [a, b, c]
```

## Advanced Patterns

### Conditional Config

Use composition type for conditional values:

```yaml
# defaults.yaml
instance_size:
  account: t3.small
  cluster: t3.large
  vpc: t3.medium

# Later reference
cluster:
  instance_type: "{{instance_size.{{composition.type}}}}"
```

### Config Reuse with Anchors

```yaml
# Base definition
base_tags: &base_tags
  ManagedBy: kompos
  Project: myapp

# Reuse and extend
account:
  tags:
    <<: *base_tags
    Type: account

cluster:
  tags:
    <<: *base_tags
    Type: cluster
```

### Multi-Composition Paths

```yaml
# .komposconfig.yaml
komposconfig:
  compositions:
    order:
      terraform:
        - account    # Run first
        - vpc        # Then VPC
        - cluster    # Then clusters
```

### Dynamic Outputs

```yaml
# Use interpolation for output paths
composition:
  instance: "{{cluster.name}}-{{region.name}}-{{env.name}}"
  # Result: web-us-east-1-prod
```

## Performance

### Large Hierarchies

For 100+ clusters:
- Use composition order to process incrementally
- Cache himl results when possible
- Exclude unused keys early

### CI/CD Integration

```bash
# Generate only changed compositions
kompos configs/.../cluster=web tfe generate --tfvars-only

# Validate before merge
kompos configs/.../cluster=web validate

# Compare with main branch
git diff main...HEAD -- configs/
```

## Extending Kompos

### Custom Runners

Create runner by extending `GenericRunner`:

```python
from kompos.runner import GenericRunner

class MyRunner(GenericRunner):
    def run(self, args, extra_args):
        # Your logic here
        pass
```

### Custom Validators

Add validation rules to `ValidateRunner`:

```python
def _validate_custom_rule(self, args):
    # Return list of issues
    return []
```

## Troubleshooting

### Debug Mode

```bash
# Verbose output
kompos -vv configs/... tfe generate

# Show all Himl operations
kompos -vvv configs/... config --format yaml
```

### Common Errors

**`No compositions detected`**
- Check directory structure has `composition=*/`
- Verify `.komposconfig.yaml` order section

**`Schema validation failed`**
- Check `.komposconfig.yaml` syntax
- Ensure all required keys present
- Validate YAML indentation

**`Module not found`**
- Check Python environment
- Reinstall: `pip install --force-reinstall kompos`

## Best Practices

1. **Start specific, refactor up** - Begin with per-cluster configs, move common patterns to shared layers
2. **Version everything in Git** - Track all config changes
3. **Use validation** - Run `validate` before generating
4. **Trace values** - Use `explore trace` to understand config sources
5. **Document overrides** - Comment why values differ from defaults
6. **Test in dev first** - New versions/configs in dev before prod
7. **Keep `.komposconfig.yaml` simple** - Minimal runtime settings
8. **Use meaningful names** - Clear composition and key names
9. **Use semantic versioning** - `v2.0.0` not `main` for module refs
10. **Always use remote state** - Never rely on local Terraform state

## Critical: Remote State Required

⚠️ **Local Terraform state is NOT preserved between runs.**

The terraform runner cleans runtime directories (`.kompos-runtime/`) before each execution:

- ❌ `terraform.tfstate` deleted
- ❌ `.terraform/` cache deleted
- ❌ Local state lost

### Required: Configure Remote Backend

You **MUST** use a remote state backend:

```hcl
# backend.tf
terraform {
  backend "s3" {
    bucket = "my-terraform-state"
    key    = "vpc/terraform.tfstate"
    region = "us-east-1"
  }
}
```

**Supported backends:**
- AWS S3, Terraform Cloud/Enterprise, Azure Blob Storage, GCS, Consul
- Any [Terraform backend](https://www.terraform.io/language/settings/backends)

**Why:**
- State persists across kompos runs
- Shared across team members
- Backed up and versioned
- Terraform best practice

## Provider Configuration

Use native Terraform variables, not generated `provider.tf.json`:

```hcl
# provider.tf (static file, version controlled)
provider "aws" {
  region = var.aws_region
  
  assume_role {
    role_arn = var.role_arn
  }
}

variable "aws_region" {
  type = string
}

variable "role_arn" {
  type = string
}
```

```yaml
# Hiera config - values passed via tfvars
aws_region: "{{region.location}}"
role_arn: "{{account.role_arn}}"
```

**Benefits:**
- Provider config in Git (auditable)
- Standard Terraform syntax
- IDE/linting support
- No JSON generation needed

## Reference

### Key Files

| File | Purpose |
|------|---------|
| `.komposconfig.yaml` | Kompos runtime settings |
| `defaults_*.yaml` | Shared defaults (tags, terraform, etc.) |
| `composition=*/` | Composition-specific configs |
| `*.tf.versioned` | Module version templates |

### Important Paths

| Path | Contents |
|------|----------|
| `generated/` | All generated files |
| `generated/clusters/` | Per-cluster terraform files |
| `generated/workspaces/` | TFE workspace configs |
| `compositions/terraform/` | Source composition templates |

### Interpolation Types

| Type | Syntax | Example |
|------|--------|---------|
| Simple | `{{key}}` | `{{cluster.name}}` |
| Nested | `{{a.b.c}}` | `{{vpc.cidr_block}}` |
| Double | `{{outer.{{inner}}}}` | `{{config.{{type}}.version}}` |

## Learn More

- **[Quick Guide](./GUIDE.md)** - Basics and quick start
- **[Examples](../examples/)** - Hands-on tutorials  
- **[HIML Docs](https://github.com/adobe/himl)** - Config engine
- **[GitHub](https://github.com/adobe/kompos)** - Source code

