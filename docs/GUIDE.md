# Kompos Usage Guide

Practical reference for using Kompos day-to-day.

## Command Reference

### Generate Files

```bash
# Generate all TFE files
kompos configs/path/to/composition tfe generate

# Generate only tfvars
kompos configs/... tfe generate --tfvars-only

# Generate only workspace config
kompos configs/... tfe generate --workspace-only

# Run local Terraform (with plan/apply/destroy)
kompos configs/... terraform plan
kompos configs/... terraform apply
```

### View Configuration

```bash
# See merged config
kompos configs/... config --format yaml

# See raw config (no exclusions) - debugging only
kompos configs/... config --skip-interpolation-validation

# Pretty print
kompos configs/... config --format json | jq
```

### Debug & Explore

```bash
# Where does this value come from?
kompos configs/... explore trace key.path

# Compare two configs
kompos configs/path1 explore compare configs/path2 --keys key1,key2

# Show directory structure
kompos configs/... explore visualize

# Analyze which files contribute keys
kompos configs/... explore analyze
```

### Validation

```bash
# Check for config errors
kompos configs/... validate

# Check specific rule
kompos configs/... validate --rule excluded-but-referenced
```

### Verbosity

```bash
kompos -v configs/... tfe generate    # INFO
kompos -vv configs/... tfe generate   # DEBUG (Kompos + Himl)
```

## How Kompos Works

### 1. Directory = Config Path

Your directory structure IS your configuration hierarchy:

```
configs/cloud=aws/env=prod/cluster=web/
        └────┘ └──┘ └────┘ └──┘
        layer  layer layer  layer
```

Deeper = more specific = overrides parent values.

### 2. Files Merge Automatically

```
defaults.yaml            # Base
  + env=prod/env.yaml    # + Prod overrides
  + cluster=web/...      # + Cluster overrides
  = Final config         # = Merged result
```

**Merge rules:**
- Dicts: Deep merge
- Lists: Replace (no merge!)
- Scalars: Override

### 3. Interpolation Resolves

`{{key.path}}` placeholders resolve from merged config:

```yaml
cluster:
  name: web
  region: us-east-1
  fullname: "{{cluster.name}}-{{region}}"  # → web-us-east-1
```

### 4. Generation Happens

- `.tf.versioned` → `main.tf` (module versions injected)
- Config → `generated.tfvars.yaml` (filtered/excluded)
- Workspace metadata → `workspace.yaml`

## Configuration Structure

### `.komposconfig.yaml` - Tool Settings

Controls HOW Kompos operates:

```yaml
komposconfig:
  defaults:
    base_dir: "./generated"
  compositions:
    order:
      terraform: [account, cluster]
    config_keys:
      excluded:
        account: [cluster, vpc]
```

**Purpose:** Execution order, output paths, exclusions

### Layered Configs - Your Data

Defines WHAT you're deploying:

```yaml
# configs/.../cluster.yaml
cluster:
  name: web
  instance_type: t3.large
```

**Purpose:** Infrastructure settings

## File Patterns

| File Pattern | Purpose |
|-------------|---------|
| `defaults_*.yaml` | Shared defaults (tags, terraform config) |
| `composition=*/` | Composition-specific overrides |
| `*.tf.versioned` | Module version templates |
| `.komposconfig.yaml` | Kompos runtime settings |

## Output Structure

```
generated/
  clusters/              # Type (from .komposconfig.yaml)
    web-prod-use1/      # Instance (from layered config)
      main.tf
      generated.tfvars.yaml
  workspaces/
    web-prod-use1.workspace.yaml
```

Three parts: `base/type/instance`

## Debugging Workflow

### Problem: Unresolved Interpolation

```
ERROR: Interpolation could not be resolved {{cluster.name}}
```

**Steps:**
1. Check if key exists: `kompos ... explore trace cluster.name`
2. Check if excluded: `grep excluded .komposconfig.yaml`
3. Check hierarchy: Does your path have required layers?

### Problem: Wrong Value

**Steps:**
1. Trace evolution: `kompos ... explore trace key.path`
2. Check files: Look at source files in trace output
3. Check YAML syntax: Indentation matters (spaces not tabs!)

### Problem: Not Merging

**Dicts merge, lists replace:**

```yaml
# Parent: [a, b]
# Child: [c]  
# Result: [c]  ← Replaces!

# For merging dicts, use YAML anchors:
base: &tags
  key1: val1
  
extended:
  <<: *tags     # Merges!
  key2: val2
```

## Common Tasks

### Change Module Version

1. Edit: `configs/env=prod/env.yaml`
   ```yaml
   vpc:
     module_version: "5.2.0"
   ```
2. Validate: `kompos configs/... validate`
3. Generate: `kompos configs/... tfe generate`
4. Review: `git diff generated/`
5. Commit: `git add configs/ generated/`

### Add New Cluster

1. Create: `configs/.../cluster=newcluster/cluster.yaml`
2. Set values: `cluster: { name: newcluster, ... }`
3. Generate: `kompos configs/.../cluster=newcluster tfe generate`
4. Verify: Check `generated/clusters/newcluster/`

### Compare Environments

```bash
kompos configs/.../env=dev explore compare \
  configs/.../env=prod \
  --keys vpc.cidr,cluster.instance_type
```

### Update Shared Config

1. Edit shared layer: `configs/cloud=aws/defaults_terraform.yaml`
2. Test one cluster: `kompos configs/.../cluster=test tfe generate`
3. Generate all: Loop through clusters or use CI/CD

## Troubleshooting

### "No compositions detected"

**Cause:** Missing `composition=*/` in path

**Fix:** Ensure path includes composition directory

### "Schema validation failed"

**Cause:** Invalid `.komposconfig.yaml` syntax

**Fix:**
- Check YAML syntax (indentation, colons)
- Validate against schema
- Ensure required keys present

### "Module not found"

**Cause:** Kompos not installed or wrong venv

**Fix:**
```bash
pip install --force-reinstall kompos
# Or activate venv
source venv/bin/activate
```

### Unresolved placeholder in output

**Cause:** Used `--skip-interpolation-validation`

⚠️ **Warning:** This flag leaves `{{placeholders}}` unresolved. Only for debugging!

**Fix:** Remove flag and resolve actual interpolation issue

## Best Practices

1. **Git everything** - Track all config changes
2. **Validate before merge** - Run `validate` in CI
3. **Test in dev first** - New versions → dev → prod
4. **Trace when confused** - `explore trace` shows hierarchy
5. **Keep configs DRY** - Start specific, refactor common patterns up
6. **Use semantic versions** - `v2.0.0` not `main` for modules
7. **Remote state required** - Never rely on local `terraform.tfstate`

## Key Concepts

### Composition Types

Logical groupings: `account`, `cluster`, `vpc`, `node-groups`

Each can have different:
- Execution order
- Output subdirectories  
- Excluded keys

### Exclusions

Exclude irrelevant config per composition:

```yaml
komposconfig:
  compositions:
    config_keys:
      excluded:
        account: [cluster, vpc]  # Account doesn't need cluster config
```

### Interpolation Types

| Type | Syntax | Use Case |
|------|--------|----------|
| Simple | `{{key}}` | Direct value |
| Nested | `{{a.b.c}}` | Nested keys |
| Double | `{{cfg.{{type}}}}` | Dynamic key path |

### Module Versioning

`.tf.versioned` files are templates:

```hcl
module "vpc" {
  version = "{{vpc.module_version}}"  # ← Resolved at generation
}
```

Enables different versions per environment without code duplication.

## Quick Fixes

| Problem | Solution |
|---------|----------|
| Wrong value | `explore trace key.path` |
| Unresolved interpolation | Check exclusions, verify key exists |
| File not generated | Check composition path has `composition=*/` |
| Changes not reflected | Regenerate with `tfe generate` |
| State lost | Configure remote backend (S3, TFE, etc.) |

## Next Steps

- **[Advanced Guide](./ADVANCED.md)** - Architecture, deep dives
- **[Examples](../examples/)** - Hands-on tutorials
- **[GitHub](https://github.com/adobe/kompos)** - Source & issues
