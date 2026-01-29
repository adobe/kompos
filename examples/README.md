# Kompos Examples

Learn Kompos through progressive, hands-on examples. Each example builds on concepts from the previous ones.

## 📚 Learning Path

### 1. [Hierarchical Configuration](features/01-hierarchical-config/)

**Learn:** How Kompos merges configuration files based on directory structure

- 🎯 **Difficulty:** Beginner
- ⏱️ **Time:** 5-10 minutes
- 📖 **Topics:** Configuration hierarchy, merging, overrides

**Key Concept:** Configuration files are layered and merged based on your path. Values at deeper levels override values
from parent levels.

```bash
cd examples/features/01-hierarchical-config
kompos config/cloud=aws/env=dev/cluster=cluster1/... config
```

---

### 2. [Module Version Pinning](features/02-module-version-pinning/)

**Learn:** How to pin Terraform module versions per environment

- 🎯 **Difficulty:** Beginner
- ⏱️ **Time:** 10-15 minutes
- 📖 **Topics:** `.tf.versioned` files, template interpolation, version management

**Key Concept:** Use `{{placeholders}}` in `.tf.versioned` files to inject module versions from hierarchical
configuration.

```bash
cd examples/features/02-module-version-pinning
kompos config/env=dev/... terraform plan --dry-run
```

---

### 3. [Configuration Exploration](features/03-config-exploration/)

**Learn:** How to explore, trace, and compare hierarchical configurations

- 🎯 **Difficulty:** Intermediate
- ⏱️ **Time:** 15-20 minutes
- 📖 **Topics:** `explore` runner, tracing values, comparing configs, visualization

**Key Concept:** Use the `explore` runner to understand where configuration values come from and how they differ across
environments.

```bash
cd examples/features/03-config-exploration
kompos config/... explore trace vpc.cidr_block
kompos config/... explore compare config/... --keys vpc.cidr_block
```

---

### 4. [TFE Multi-Cluster Management](features/04-tfe-multi-cluster/)

**Learn:** Complete workflow for managing multiple Terraform Enterprise (TFE) clusters

- 🎯 **Difficulty:** Advanced
- ⏱️ **Time:** 30-45 minutes
- 📖 **Topics:** TFE integration, per-cluster compositions, multi-environment strategy, production workflows

**Key Concept:** Generate per-cluster TFE workspaces with different module versions, provider configs, and
infrastructure sizing based on environment (dev/prod).

```bash
cd examples/features/04-tfe-multi-cluster
kompos data/cloud=aws/.../cluster=demo-cluster-01/... tfe generate
```

---

## 🎓 Recommended Learning Path

### For Complete Beginners

1. Start with **01-hierarchical-config** to understand the basics
2. Move to **02-module-version-pinning** to learn templating
3. Try **03-config-exploration** to debug and understand your configs
4. Tackle **04-tfe-multi-cluster** when ready for production patterns

### For Experienced Users

- Jump to **04-tfe-multi-cluster** for a complete production example
- Reference **03-config-exploration** for advanced debugging techniques

---

## 📊 Example Comparison

| Example                       | Focus             | Complexity | Production Ready | Time      |
|-------------------------------|-------------------|------------|------------------|-----------|
| **01-hierarchical-config**    | Config basics     | ⭐ Low      | Concept only     | 5-10 min  |
| **02-module-version-pinning** | Versioning        | ⭐⭐ Medium  | Yes              | 10-15 min |
| **03-config-exploration**     | Debugging         | ⭐⭐ Medium  | Tool demo        | 15-20 min |
| **04-tfe-multi-cluster**      | Complete workflow | ⭐⭐⭐ High   | Yes              | 30-45 min |

---

## 🔧 Prerequisites

Before starting, ensure you have:

- ✅ Kompos installed (`pip install kompos` or from source)
- ✅ Terraform installed (for examples 2 and 4)
- ✅ Basic understanding of:
    - YAML syntax
    - Terraform basics (for examples 2 and 4)
    - Hierarchical configuration concepts (helpful but not required)

---

## 💡 Tips

### Running Examples

Each example can be run independently:

```bash
# Navigate to the example directory
cd examples/features/XX-example-name/

# Follow the README.md instructions
cat README.md
```

### Experimentation

Feel free to:

- ✅ Modify configuration values
- ✅ Add new hierarchy levels
- ✅ Change module versions
- ✅ Create new clusters/environments
- ✅ Break things and fix them (best way to learn!)

### Getting Help

- 📖 **Documentation:** See `/docs/` directory
    - `ARCHITECTURE.md` - Overall design
    - `EXPLORE_RUNNER.md` - Exploration tools
    - `TFE_RUNNER.md` - TFE/TFC workflows and workspace management

- 💬 **Community:** [GitHub Issues](https://github.com/adobe/kompos/issues)

---

## 🎯 Next Steps

After completing these examples:

1. **Adapt for your infrastructure**
    - Replace example modules with your own
    - Customize naming conventions
    - Add your specific resources

2. **Integrate with your workflow**
    - Add to CI/CD pipelines
    - Configure git workflows
    - Set up team processes

3. **Explore advanced features**
    - Custom runners
    - Plugin system
    - Advanced himl features

---

## 📁 Example File Structure

```
examples/
├── README.md (this file)
└── features/
    ├── 01-hierarchical-config/
    │   ├── README.md
    │   └── config/
    ├── 02-module-version-pinning/
    │   ├── README.md
    │   ├── config/
    │   └── compositions/
    ├── 03-config-exploration/
    │   ├── README.md
    │   └── config/
    └── 04-tfe-multi-cluster/
        ├── README.md
        ├── QUICK_START.md
        ├── data/
        └── compositions/
```

---

## 🤝 Contributing

Found an issue or want to improve an example?

1. Check existing [issues](https://github.com/adobe/kompos/issues)
2. Submit a pull request with improvements
3. Share your use cases and examples

---

Happy learning! 🚀

