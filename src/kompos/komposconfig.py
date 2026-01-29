# Copyright 2019 Adobe. All rights reserved.
# This file is licensed to you under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License. You may obtain a copy
# of the License at http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software distributed under
# the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR REPRESENTATIONS
# OF ANY KIND, either express or implied. See the License for the specific language
# governing permissions and limitations under the License.

import logging
import os
from functools import reduce

import fastjsonschema
import yaml
from packaging.version import Version

from kompos import __version__

logger = logging.getLogger(__name__)

CONFIG_SCHEMA_PATH = "data/config_schema.json"


def get_value_or(dictionary, x_path, default=None):
    """
    Try to retrieve a value from a dictionary. Return the default if no such value is found.
    """
    keys = x_path.split("/")
    return reduce(
        lambda d, key: d.get(key, default)
        if isinstance(d, dict) else default, keys, dictionary)


class KomposConfig:
    """
    Parses all the available configuration files in order and merges them together.
    """

    DEFAULT_PATHS = [
        '/etc/kompos/.komposconfig.yaml',
        os.path.expanduser('~/.komposconfig.yaml'),
        os.path.join(os.getcwd(), '.komposconfig.yaml')
    ]

    def __init__(self, console_args, package_dir):
        self.config = dict()
        self.package_dir = package_dir
        self.validate = fastjsonschema.compile(self.read_schema())

        paths = self.DEFAULT_PATHS[:]

        parsed_files = []
        logger.debug(f"parsing {paths}")

        for config_path in paths:
            config_path = os.path.realpath(os.path.expanduser(config_path))
            if os.path.isfile(config_path):
                logger.debug(f"parsing {config_path}")
                with open(config_path) as f:
                    try:
                        config = yaml.safe_load(f.read())
                    except Exception as e:
                        logger.error(f"Failed to parse configuration file: {config_path}")
                        raise e

                    if isinstance(config, dict):
                        parsed_files.append(config_path)
                        self.config.update(config)
                    else:
                        logger.error(f"cannot parse yaml dict from file: {config_path}")

                try:
                    self.validate(config)
                except fastjsonschema.exceptions.JsonSchemaException as e:
                    logger.error(f"Schema validation failed for configuration file: {config_path}")
                    raise e

        self.parsed_files = parsed_files
        logger.debug(f"final kompos config: {self.config} from {parsed_files}")
        logger.debug(f"Loaded config from {', '.join([os.path.basename(f) for f in parsed_files])}")

    @property
    def kompos(self):
        """Quick access to komposconfig namespace"""
        return self.config.get('komposconfig', {})

    def read_schema(self):
        with open(os.path.join(self.package_dir, CONFIG_SCHEMA_PATH), "r") as f:
            return yaml.safe_load(f.read())

    def __contains__(self, item):
        return item in self.config

    def __getitem__(self, item):
        """
        Access komposconfig namespace items.
        All config must be under 'komposconfig' key.
        """
        if item not in self.kompos:
            raise KeyError(f"{item} not found in komposconfig namespace from {self.parsed_files}")

        return self.kompos[item]

    def vault_backend(self):
        if get_value_or(self.config, "vault/enabled"):
            os.environ["VAULT_ADDR"] = get_value_or(self.config, "vault/url")
            os.environ["VAULT_NAMESPACE"] = get_value_or(self.config, "vault/vault_namespace")
            os.environ["VAULT_USERNAME"] = get_value_or(self.config, "vault/svc_ldap_user")
            os.environ["VAULT_ROLE"] = get_value_or(self.config, "vault/svc_ldap_user_role")
            logger.info("Vault backend enabled")

    def validate_version(self):
        """Validate minimum required Kompos version"""
        min_kompos_version = self.get_kompos_setting("min_version")

        if not min_kompos_version:
            return

        if Version(__version__) < Version(min_kompos_version):
            raise Exception(
                f"The current kompos version '{__version__}' is lower than "
                f"the minimum required version '{min_kompos_version}'"
            )

    # ====================================================================================
    # Unified Configuration Access Methods
    # ====================================================================================
    def get_kompos_setting(self, path, default=None):
        """
        Get any setting from komposconfig namespace using dot-separated path.
        
        Args:
            path: Dot-separated path (e.g., 'compositions.properties.account.output_subdir')
            default: Default value if not found
        
        Returns:
            Value at path or default
            
        Examples:
            self.get_kompos_setting('terraform.version', 'latest')
            self.get_kompos_setting('compositions.properties.account.output_subdir', 'accounts')
        """
        return get_value_or(self.kompos, path.replace('.', '/'), default)

    def get_hierarchical_setting(self, runner, key, default=None):
        """
        Get setting with hierarchical lookup (DRY method for all hierarchical access).
        
        Lookup order:
        1. komposconfig.{runner}.{key}  (runner-specific)
        2. komposconfig.compositions.source.{key}  (for path-related keys)
        3. komposconfig.defaults.{key}  (global defaults)
        4. default parameter
        
        Args:
            runner: Runner name (e.g., 'terraform', 'tfe', 'helmfile')
            key: Setting key to lookup
            default: Default value if not found
        
        Returns:
            Setting value with hierarchical fallback
            
        Examples:
            self.get_hierarchical_setting('tfe', 'base_dir', './generated')
            self.get_hierarchical_setting('terraform', 'local_path', './compositions')
        """
        # 1. Check runner-specific setting
        if runner in self.kompos and key in self.kompos[runner]:
            value = self.kompos[runner][key]
            # Expand paths for local_path
            if key == 'local_path':
                return os.path.expanduser(value)
            return value

        # 2. Check composition source (for path-related keys)
        if key in ['local_path', 'root_path']:
            source = self.kompos.get('compositions', {}).get('source', {})
            if key in source:
                value = source[key]
                if key == 'local_path':
                    return os.path.expanduser(value)
                return value

        # 3. Check global defaults
        defaults = self.kompos.get('defaults', {})
        if key in defaults:
            return defaults[key]

        # 4. Return provided default
        return default

    # ====================================================================================
    # Composition Configuration Methods
    # ====================================================================================

    def excluded_config_keys(self, composition, default=[]):
        """Get excluded keys for a composition type"""
        return self.get_kompos_setting(f"compositions.config_keys.excluded.{composition}", default)

    def filtered_output_keys(self, composition, default=[]):
        """Get filtered keys for a composition type"""
        return self.get_kompos_setting(f"compositions.config_keys.filtered.{composition}", default)

    def composition_order(self, composition, default=[]):
        """Get execution order for compositions"""
        return self.get_kompos_setting(f"compositions.order.{composition}", default)

    # ====================================================================================
    # Runner Configuration Methods
    # ====================================================================================

    def runner_version(self, runner):
        """Get runner version with fallback to 'latest'"""
        return self.get_kompos_setting(f"{runner}.version", 'latest')

    def terraform_versioned_module_sources_enabled(self):
        """Check if Terraform versioned module sources feature is enabled"""
        return self.get_kompos_setting("terraform.versioned_module_sources", True)

    def repo_url(self, runner):
        """Get repository URL for a runner"""
        return self.kompos[runner]['repo']['url']

    def repo_name(self, runner):
        """Get repository name for a runner"""
        return self.kompos[runner]['repo']['name']

    def root_path(self, runner):
        """
        Get root_path with hierarchical lookup.
        Uses unified get_hierarchical_setting method.
        """
        return self.get_hierarchical_setting(runner, 'root_path', '')

    def local_path(self, runner):
        """
        Get local_path with hierarchical lookup.
        Uses unified get_hierarchical_setting method.
        """
        return self.get_hierarchical_setting(runner, 'local_path', './compositions')

    def get_runtime_setting(self, runner, key, default=None):
        """
        Get Kompos runtime setting from .komposconfig.yaml with hierarchical lookup.
        Uses unified get_hierarchical_setting method.
        
        IMPORTANT: This reads Kompos tool configuration (.komposconfig.yaml),
                   NOT layered/application config (configs/ directory).
        
        Runtime settings control Kompos behavior:
          - Where to find/generate files (paths, directories)
          - How to format output (yaml/json, extensions)
          - What to exclude (system keys, config keys)
          - Tool versions and feature flags
        
        Args:
            runner: Runner name (e.g., 'terraform', 'tfe')
            key: Setting key to lookup
            default: Default value if not found anywhere
        
        Returns:
            Runtime setting value from .komposconfig.yaml
            
        Examples:
            base_dir = kompos_config.get_runtime_setting('tfe', 'base_dir', './generated')
            fmt = kompos_config.get_runtime_setting('tfe', 'tfvars_format', 'yaml')
        """
        return self.get_hierarchical_setting(runner, key, default)

    # ====================================================================================
    # Composition Output & Naming Methods
    # ====================================================================================

    def get_composition_output_dir(self, base_dir, composition):
        """
        Get output directory for a composition with hierarchical lookup.
        
        Args:
            base_dir: Base directory for output
            composition: Composition name (e.g., 'cluster', 'account')
        
        Returns:
            Full path: {base_dir}/{output_subdir}/
        """
        output_subdir = self.get_kompos_setting(
            f"compositions.properties.{composition}.output_subdir",
            composition  # Fallback to composition name
        )
        return os.path.join(base_dir, output_subdir)

    def get_composition_name(self, raw_config, get_nested_value_fn):
        """
        Get the resolved composition instance identifier from layered config.
        
        Reads composition.instance which is defined with pure Himl interpolation:
          composition.instance: "{{account.name}}"  or  "{{cluster.fullName}}"
        
        Himl resolves the interpolation, returning the actual instance identifier:
        - account compositions: "my-account"
        - cluster compositions: "my-cluster-us-east-1"
        
        Args:
            raw_config: Himl-generated configuration dictionary
            get_nested_value_fn: Function to extract nested values from raw_config
            
        Returns:
            Resolved instance identifier (e.g., "my-account", "my-cluster-us-east-1")
        """
        import logging
        logger = logging.getLogger(__name__)

        # Read resolved composition instance from layered config (pure interpolation)
        name = get_nested_value_fn(raw_config, 'composition.instance')

        if name and '{{' not in str(name):
            logger.debug(f"Using composition instance from layered config: '{name}'")
            return name

        # Fallback if not defined or unresolved
        logger.warning("No resolved composition.instance in layered config")
        return None
