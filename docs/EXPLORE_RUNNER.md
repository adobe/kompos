# Explore Runner: Configuration Analysis and Visualization

The `explore` runner provides powerful tools to understand, analyze, and visualize your hierarchical configuration structure. It helps you answer questions like:
- Where does this value come from?
- What does each layer/file contribute?
- How are values inherited and overridden?
- Which files add the most configuration?

## Commands Overview

```bash
kompos <config_path> explore analyze     # Analyze variable distribution across hierarchy
kompos <config_path> explore trace       # Trace a specific variable through layers
kompos <config_path> explore visualize   # Visualize hierarchy structure
kompos <config_path> explore compare     # Compare configurations across paths
```

---

## 1. Analyze: Configuration Distribution

Shows what variables are defined at each hierarchy level and tracks new vs. overridden keys.

### Usage

```bash
kompos <config_path> explore analyze
```

### Example Output

```
================================================================================
HIERARCHICAL CONFIGURATION ANALYSIS
================================================================================
Config Path: configs/cloud=aws/project=demo/env=dev/region=us-west-2/cluster=main
Total Layers: 6

Layer: configs
  New Variables: 0
  Overridden Variables: 0
  Unchanged: 0

Layer: configs/cloud=aws
  New Variables: 45
    + cloud.name
    + cloud.provider
    + cluster.fullName
    + defaults_cluster.version
    + region.name
    ... and 40 more
  Overridden Variables: 0
  Unchanged: 0

Layer: configs/cloud=aws/project=demo
  New Variables: 3
    + project.name
    + project.cost_center
  Overridden Variables: 1
    ~ cluster.fullName
  Unchanged: 44
```

### Color Legend
- 🟢 **Green** - New variables (+ symbol)
- 🟡 **Yellow** - Overridden variables (~ symbol)
- ⚪ **Dim white** - Unchanged count

---

## 2. Trace: Value Provenance

Trace a specific configuration key through the hierarchy to see where it originates and how it changes.

### Usage

```bash
kompos <config_path> explore trace --key <key.path>
```

### Examples

```bash
# Trace cluster name
kompos configs/.../cluster explore trace --key cluster.fullName

# Trace VPC CIDR
kompos configs/.../cluster explore trace --key vpc.cidr

# Trace nested values
kompos configs/.../cluster explore trace --key node_groups.default.instance_types
```

### Example Output

```
================================================================================
VALUE TRACE: cluster.fullName
================================================================================
Config Path: configs/cloud=aws/project=demo/env=dev/region=us-west-2/cluster=main

  configs
    Value: None [UNDEFINED]

  configs/cloud=aws
    Value: default-{{region.name}}-{{env.name}}-{{project.name}} [NEW]

  configs/cloud=aws/project=demo
    Value: default-{{region.name}}-{{env.name}}-demo [INTERP]
                                            ^^^^
  configs/cloud=aws/project=demo/env=dev
    Value: default-{{region.name}}-dev-demo [INTERP]
                                    ^^^
  configs/.../region=us-west-2
    Value: default-us-west-2-dev-demo [INTERP]
           ^^^^^^^^^^^^^^^^
  configs/.../cluster=main
    Value: default-us-west-2-dev-demo

  configs/.../composition=cluster
    Value: main-us-west-2-dev-demo [OVERRIDE]
           ^^^^
```

### Status Tags
- 🟢 **[NEW]** - First appearance of this key
- 🔵 **[INTERP]** - Interpolation resolved (fewer `{{}}` tokens)
- 🟡 **[OVERRIDE]** - Value changed (different pattern)
- ⚪ (no tag) - Inherited unchanged
- 🔴 **[UNDEFINED]** - Key not set at this level

### Features
- **Highlighted differences** - Changed portions are underlined/highlighted
- **Interpolation tracking** - Shows progressive token resolution
- **Full path visibility** - See exact hierarchy traversal

---

## 3. Visualize: Hierarchy Structure

Generate visual representations of your configuration hierarchy showing structure, file contributions, and variable counts.

### Text Output (Default)

```bash
kompos <config_path> explore visualize
```

### Example Output

```
================================================================================
CONFIGURATION HIERARCHY VISUALIZATION
================================================================================
Root Path: configs/cloud=aws/project=demo/env=dev/region=us-west-2/cluster=main
Total Layers: 7

Variable Contributions by Layer:
Total Variables: 325

  +83                configs/cloud=aws
                       • defaults_terraform.yaml (+32 new)
                       • defaults_cluster.yaml (+18 new)
                       • defaults_vpc.yaml (+15 new)
                       • cloud.yaml (+6 new, ~2 interp)

  +74                configs/.../composition=cluster
                       • cluster.yaml (+50 new, ~15 interp, !9 override)

  +54                configs/.../region=us-west-2
                       • region.yaml (+49 new)
                       • (interpolation inheritance) (+5) ← from parent layer

────────────────────────────────────────────────────────────────────────────────

├─ configs
   Variables: 77
     • global_clouds.yaml (+45)
     • global_regions.yaml (+32)

  ├─ configs/cloud=aws
     Variables: 160 (+83)
       • cloud.yaml (+6, ~2)
       • defaults_cluster.yaml (+18)
       • defaults_terraform.yaml (+32)
       • defaults_vpc.yaml (+15)

    ├─ configs/cloud=aws/project=demo
       Variables: 170 (+10)
         • project.yaml (+8, ~2)

────────────────────────────────────────────────────────────────────────────────

Legend:
  +N    New keys (first appearance)
  ~N    Interpolation resolved (fewer {{}} tokens)
  !N    Override (value changed)
  (interpolation inheritance) Keys inherited through HIML merge from parent layers
```

### GraphViz Diagram

Generate a visual flowchart diagram:

```bash
kompos <config_path> explore visualize --format dot --output-file hierarchy.dot
dot -Tpng hierarchy.dot -o hierarchy.png
open hierarchy.png
```

**Or use online viewer** (no installation needed):
1. Generate DOT file: `kompos ... explore visualize --format dot --output-file hierarchy.dot`
2. Visit: https://dreampuf.github.io/GraphvizOnline/
3. Paste contents and view instantly!

#### Diagram Features
- 🟢 **Color-coded nodes** - Green (small), Cyan (medium), Yellow (large configs)
- 📊 **Detailed labels** - Path, total vars, delta per layer
- 📁 **File contributions** - Shows which files contribute how many keys
- ➕ **Edge labels** - Shows how many vars each layer adds
- 📖 **Built-in legend** - Explains colors and symbols

---

## 4. Compare: Cross-Environment Comparison

Compare configuration values across different paths in your hierarchy.

### Usage

```bash
# Compare all keys across paths
kompos <config_path> explore compare

# Compare specific keys
kompos <config_path> explore compare --keys vpc.cidr cluster.name region.location
```

### Example Output

```
================================================================================
CONFIGURATION COMPARISON MATRIX
================================================================================

Key: vpc.cidr
  configs/.../env=dev/region=us-west-2: 10.1.0.0/16
  configs/.../env=dev/region=us-east-1: 10.2.0.0/16
  configs/.../env=prod/region=us-west-2: 10.10.0.0/16

Key: cluster.instance_type
  configs/.../env=dev: t3.medium
  configs/.../env=prod: m5.xlarge
```

---

## Common Patterns

### Debug Missing Value

```bash
# Find where a key is defined
kompos <path> explore trace --key missing.key.path

# If not found, you'll see:
# ⚠️  Key 'missing.key.path' not found. It may be a dictionary.
# Suggested keys:
#   • missing.key.other_path
#   • missing.other.path
```

### Find Configuration Bloat

```bash
# See which files/layers add the most keys
kompos <path> explore visualize

# Look at the top of the summary:
# +83  configs/cloud=aws       ← Biggest contributor
# +74  configs/.../composition
```

### Understand Interpolation

```bash
# Trace a value with interpolation tokens
kompos <path> explore trace --key cluster.fullName

# You'll see progressive resolution:
# {{region.name}}-{{env.name}} [NEW]
# us-west-2-{{env.name}}       [INTERP]  ← region resolved
# us-west-2-dev                [INTERP]  ← env resolved
```

### Verify Overrides

```bash
# Check if dev overrides prod defaults
kompos configs/.../env=dev/cluster=test explore trace --key cluster.instance_type

# Look for [OVERRIDE] tags to see where values change
```

---

## Integration with Other Commands

### Combine with Config Output

```bash
# Trace where a key comes from
kompos <path> explore trace --key vpc.cidr

# Then view the full VPC configuration
kompos <path> config --filter vpc
```

### Debug Before Running

```bash
# Visualize hierarchy first
kompos <path> explore visualize

# Verify key values
kompos <path> explore trace --key cluster.name

# Then run Terraform
kompos <path> terraform plan
```

---

## Performance Tips

- **Use specific paths**: The deeper you start in the hierarchy, the faster the analysis
- **Filter early**: Use `--filter` to focus on specific sections
- **Skip secrets**: Add `--skip-secrets` for faster iteration during development

---

## Troubleshooting

### "Key not found" Errors

If trace shows a key doesn't exist:
1. Check the suggested keys - you might have the path slightly wrong
2. Use `config` to see all available keys: `kompos <path> config --format yaml`
3. The key might only exist after interpolation - try with full hierarchy

### Slow Analysis

For very large hierarchies:
1. Start from a deeper path (closer to the leaf)
2. Use `--skip-secrets` to avoid secret resolution overhead
3. Use `--filter` to limit analysis scope

### GraphViz Installation

**macOS:**
```bash
brew install graphviz
```

**Ubuntu/Debian:**
```bash
sudo apt-get install graphviz
```

**Or use online**: https://dreampuf.github.io/GraphvizOnline/

---

## Advanced Usage

### Save Analysis for Documentation

```bash
# Generate markdown report
kompos <path> explore analyze --format markdown --output-file analysis.md

# Generate visual diagram
kompos <path> explore visualize --format dot --output-file hierarchy.dot
dot -Tsvg hierarchy.dot -o hierarchy.svg
```

### Automate Comparisons

```bash
# Compare dev vs prod
for env in dev prod; do
  echo "=== $env ==="
  kompos configs/cloud=aws/env=$env/cluster=main explore analyze
done
```

### Export Raw Data

```bash
# Get JSON for custom processing
kompos <path> explore visualize --format json --output-file hierarchy.json

# Process with jq
jq '.layers[] | {path: .path, vars: .var_count}' hierarchy.json
```

---

## See Also

- [Architecture Documentation](./ARCHITECTURE.md) - Understanding hierarchy and file generation
- [TFE Runner Documentation](./TFE_RUNNER.md) - Terraform Enterprise workflow
- [HIML Documentation](https://github.com/adobe/himl) - Underlying hierarchical config engine
