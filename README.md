# kompos

[![Build Status](https://www.travis-ci.com/adobe/kompos.svg?token=8uHqfhgsxdvJ93qWAxhn&branch=main)](https://www.travis-ci.com/adobe/kompos) [![Docker pull](https://img.shields.io/docker/pulls/adobe/kompos)](https://hub.docker.com/r/adobe/kompos) [![](https://images.microbadger.com/badges/version/adobe/kompos.svg)](https://microbadger.com/images/adobe/kompos "Get your own version badge on microbadger.com") [![License](https://img.shields.io/github/license/adobe/kompos)](https://github.com/adobe/kompos/blob/master/LICENSE) [![PyPI pyversions](https://img.shields.io/pypi/pyversions/kompos.svg)](https://pypi.python.org/pypi/kompos/)

![kompos](img/kompos.png)

**Kompos** is a configuration-driven tool for managing infrastructure provisioning
and deployment. It uses a hierarchical folder structure and YAML files to store
and generate configurations, with runtime value interpolation and injection into
any runner. Terraform and helmfile are supported as built-in provisioners, but
the architecture supports custom runners for any tool or platform.

## Key Features

- **Hierarchical Configuration**: Layer configurations across environments, regions, and compositions with automatic merging and inheritance
- **Runtime Value Interpolation**: Dynamically generate and inject configuration values into any runner at execution time
- **Universal Runner Architecture**: Built-in support for Terraform and Helmfile, extensible for any provisioning or deployment tool
- **Configuration Analysis**: Powerful inspection tools to understand hierarchy, trace variable origins, and visualize data flow
- **Multi-Environment Support**: Unified configuration structure that works across any cloud provider or infrastructure platform

### Core Benefits

- ✅ **DRY (Don't Repeat Yourself)**: Define common values once at higher levels, override only what differs per environment
- ✅ **Clear Precedence**: More specific (deeper) configurations automatically override general ones
- ✅ **Flexible Structure**: Organize by cloud, environment, cluster, composition, or any hierarchy that fits your workflow
- ✅ **Environment-Specific Overrides**: Dev can use different values than prod (e.g., smaller instances, test versions)
- ✅ **Easy Maintenance**: Change one file to affect multiple clusters/environments at once
- ✅ **Clean Separation**: Source files (version controlled) vs. generated files (runtime artifacts)

Below is a graphical representation of the data flow, showing how hierarchical 
configurations are merged and interpolated before being injected into runners:

![kompos-data-flow](img/kompos-diagram.svg)

## Installation

**Requirements:** Python 3.11 or higher

### PyPI (Recommended for Users)

```bash
# Install
pip install kompos

# Upgrade to latest version
pip install --upgrade kompos
```

### Using Virtual Environment (Recommended)

Using virtualenv for isolated installation:

```bash
pip install virtualenv
virtualenv kompos-env
source kompos-env/bin/activate
(kompos-env) pip install kompos
(kompos-env) pip install --upgrade kompos
(kompos-env) kompos --version
```

### Locally for Development

Using virtualenv with editable install:

```bash
pip install virtualenv
virtualenv .env
source .env/bin/activate
(env) cd kompos/
(env) pip install --editable .
```

## Documentation

Comprehensive guides for understanding and using Kompos:

- **[📚 Architecture & File Generation](./docs/ARCHITECTURE.md)** - How hierarchical configuration works, file generation, and merge behavior
- **[📊 Explore Runner](./docs/EXPLORE_RUNNER.md)** - Configuration analysis, value tracing, and hierarchy visualization
- **[🔧 TFE Runner](./docs/TFE_RUNNER.md)** - Terraform Enterprise workflow and workspace generation

## Hierarchical Configuration

Kompos leverages [himl](https://github.com/adobe/himl) to provide a
[hiera](https://puppet.com/docs/puppet/latest/hiera_intro.html#concept-7256)-like
hierarchical configuration structure. This enables:

- **Configuration Inheritance**: Define base configurations and override them per environment, cluster, or composition
- **Value Interpolation**: Reference and reuse values across your configuration hierarchy
- **Runtime Injection**: Generated configurations are automatically interpolated and injected into Terraform/Helmfile at execution time
- **Configuration Analysis**: Trace variable origins, visualize data flow, and compare configurations across environments
- **DRY Principle**: Eliminate configuration duplication across environments

## Examples

The [`examples/features/`](./examples/features/) directory contains working examples demonstrating key Kompos capabilities:

### [Hierarchical Configuration](./examples/features/hierarchical/)
Demonstrates how configuration files are layered and merged based on directory paths:
- Configuration inheritance and overrides
- Environment-specific values
- Multi-level hierarchies (cloud → environment → cluster → composition)

### [Versioned Module Sources](./examples/features/versioned-sources/)
Shows how to use `.tf.versioned` template files for per-environment Terraform module version pinning:
- Dynamic module source interpolation
- Per-cluster/environment version management
- Gradual rollout patterns (test in dev, promote to prod)
- Overcoming Terraform's static `source` limitation

Each example includes a README with usage instructions and explanations.

## Usage

Kompos reads hierarchical configurations, interpolates runtime values, and injects them into the appropriate runner:

```bash
# Terraform: hierarchical config values are injected as tfvars
kompos <config_path> terraform <command>

# Helmfile: hierarchical config values are interpolated and injected
kompos <config_path> helmfile <command>

# TFE: generate workspace configs and tfvars for Terraform Enterprise
kompos <config_path> tfe generate

# Explore: discover and analyze configuration hierarchy and data flow
kompos <config_path> explore <analyze|trace|visualize|compare>

# View the generated configuration before running
kompos <config_path> config --format yaml
```

The runner architecture is extensible - you can create custom runners for any tool that needs configuration injection.

### Common Config Commands

The `config` command supports all HIML arguments natively for flexible configuration viewing and debugging:

```bash
# Example path from hierarchical example
CONFIG_PATH="examples/features/hierarchical/config/cloud=aws/env=dev/cluster=cluster1/composition=terraform/terraform=cluster"

# View full merged configuration
kompos $CONFIG_PATH config

# View as JSON
kompos $CONFIG_PATH config --format json

# Filter: show only specific keys
kompos $CONFIG_PATH config --filter cluster --filter vpc

# Exclude: hide specific keys
kompos $CONFIG_PATH config --exclude terraform --exclude composition

# Save to file
kompos $CONFIG_PATH config --output-file merged-config.yaml

# Wrap output under a key (useful for Terraform)
kompos $CONFIG_PATH config --enclosing-key config

# Skip interpolation validation (useful for templates with missing values)
kompos $CONFIG_PATH config --skip-interpolation-validation

# Skip secret resolution (faster for debugging)
kompos $CONFIG_PATH config --skip-secrets

# Combine multiple options
kompos $CONFIG_PATH config \
  --filter cluster --filter vpc \
  --format json \
  --output-file cluster-vpc.json \
  --skip-secrets
```

**Tip:** Use `--filter` to inspect specific sections of your configuration during development and debugging.

## Docker Image

Docker images are not currently maintained. Please use PyPI installation for the latest version.
Docker image [adobe/kompos](https://hub.docker.com/r/adobe/kompos)

## License

[Apache License 2.0](/LICENSE)
