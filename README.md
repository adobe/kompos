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
- **Multi-Environment Support**: Unified configuration structure that works across any cloud provider or infrastructure platform

Below is a graphical representation of the data flow, showing how hierarchical 
configurations are merged and interpolated before being injected into runners:

![kompos-data-flow](img/kompos-diagram.svg)

## Installation

**Requirements:** Python 3.11 or higher

### PyPI

```bash
pip install kompos
```

### Locally for development

Using virtualenv

```bash
pip install virtualenv
virtualenv .env
source .env/bin/activate
(env) cd kompos/
(env) pip install --editable .
```

## Hierarchical Configuration

Kompos leverages [himl](https://github.com/adobe/himl) to provide a
[hiera](https://puppet.com/docs/puppet/latest/hiera_intro.html#concept-7256)-like
hierarchical configuration structure. This enables:

- **Configuration Inheritance**: Define base configurations and override them per environment, cluster, or composition
- **Value Interpolation**: Reference and reuse values across your configuration hierarchy
- **Runtime Injection**: Generated configurations are automatically interpolated and injected into Terraform/Helmfile at execution time
- **DRY Principle**: Eliminate configuration duplication across environments

Checkout the [examples](./examples) for more information.

## Usage

Kompos reads hierarchical configurations, interpolates runtime values, and injects them into the appropriate runner:

```bash
# Terraform: hierarchical config values are injected as tfvars
kompos <config_path> terraform <command>

# Helmfile: hierarchical config values are interpolated and injected
kompos <config_path> helmfile <command>

# View the generated configuration before running
kompos <config_path> config --format yaml
```

The runner architecture is extensible - you can create custom runners for any tool that needs configuration injection.

## Docker Image

Docker images are not currently maintained. Please use PyPI installation for the latest version.
Docker image [adobe/kompos](https://hub.docker.com/r/adobe/kompos)

## License

[Apache License 2.0](/LICENSE)
