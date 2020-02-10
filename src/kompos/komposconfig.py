# Copyright 2019 Adobe. All rights reserved.
# This file is licensed to you under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License. You may obtain a copy
# of the License at http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software distributed under
# the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR REPRESENTATIONS
# OF ANY KIND, either express or implied. See the License for the specific language
# governing permissions and limitations under the License.

import os
import yaml
import logging
import fastjsonschema
from pathlib import Path

from functools import reduce
from distutils.version import StrictVersion
from kompos import __version__

logger = logging.getLogger(__name__)

CONFIG_SCHEMA_PATH = "data/config_schema.json"

# The filename of the generated hierarchical configuration for Terrraform.
TERRAFORM_CONFIG_FILENAME = "variables.tfvars.json"

# The filename of the generated Terrraform provider.
TERRAFORM_PROVIDER_FILENAME = "provider.tf.json"

# The filename of the generated hierarchical configuration for Helmfile.
HELMFILE_CONFIG_FILENAME = "hiera-generated.yaml"

# Directory to store terraform plugin cache
TERRAFORM_CACHE_DIR = "~/.kompos/.terraform.d/plugin-cache"


def local_config_dir(directory=TERRAFORM_CACHE_DIR):
    try:
        Path(Path.expanduser(Path(directory))).mkdir(parents=True, exist_ok=True)
        return Path.expanduser(Path(directory))

    except IOError:
        logging.error("Failed to create dir in path: %s", directory)


def get_value_or(dictionary, x_path, default=None):
    """
    Try to retrieve a value from a dictionary. Return the default if no such value is found.
    """
    keys = x_path.split("/")
    return reduce(
        lambda d, key: d.get(key, default)
        if isinstance(d, dict) else default, keys, dictionary)


class KomposConfig():
    """
    Parses all the available configuration files in order and merges them together.
    """

    DEFAULT_PATHS = [
        '/etc/kompos/.komposconfig.yaml',
        os.path.expanduser('~/.komposconfig.yaml'),
        os.path.join(os.getcwd(), '.komposconfig.yaml')
    ]

    def __init__(self, console_args, package_dir):
        cluster_config_path = console_args.cluster_config_path
        self.config = dict()
        self.package_dir = package_dir
        self.validate = fastjsonschema.compile(self.read_schema())

        paths = self.DEFAULT_PATHS[:]

        parsed_files = []
        logger.debug("parsing %s", paths)

        for config_path in paths:
            config_path = os.path.realpath(os.path.expanduser(config_path))
            if os.path.isfile(config_path):
                logger.info("parsing %s", config_path)
                with open(config_path) as f:
                    try:
                        config = yaml.safe_load(f.read())
                    except Exception as e:
                        logger.error("Failed to parse configuration file: %s", config_path)
                        raise e

                    if isinstance(config, dict):
                        parsed_files.append(config_path)
                        self.config.update(config)
                    else:
                        logger.error(
                            "cannot parse yaml dict from file: %s", config_path)

                try:
                    self.validate(config)
                except fastjsonschema.exceptions.JsonSchemaException as e:
                    logger.error("Schema validation failed for configuration file: %s", config_path)
                    raise e

        self.parsed_files = parsed_files
        logger.info("final kompos config: %s from %s", self.config, parsed_files)

    def get(self, item, default=None):
        return self.config.get(item, default)

    def validate_version(self):
        min_kompos_version = get_value_or(self.config, "min_version")

        if not min_kompos_version:
            return

        if StrictVersion(__version__) < StrictVersion(min_kompos_version):
            raise Exception(
                "The current kompos version '{}' is lower than the minimum required version '{}'".format(
                    __version__, min_kompos_version,
                )
            )

    def read_schema(self):
        with open(os.path.join(self.package_dir, CONFIG_SCHEMA_PATH), "r") as f:
            return yaml.safe_load(f.read())

    def __contains__(self, item):
        return item in self.config

    def __getitem__(self, item):
        if item not in self.config:
            raise KeyError("%s not found in %s" % (item, self.parsed_files))

        return self.config[item]

    def all(self):
        return self.config

    def vault_backend(self):
        if get_value_or(self.config, "vault/enabled"):
            os.environ["VAULT_ADDR"] = get_value_or(self.config, "vault/url")
            os.environ["VAULT_NAMESPACE"] = get_value_or(self.config, "vault/vault_namespace")
            os.environ["VAULT_USERNAME"] = get_value_or(self.config, "vault/svc_ldap_user")
            os.environ["VAULT_ROLE"] = get_value_or(self.config, "vault/svc_ldap_user_role")
            logger.info("Vault backend enabled")

    def excluded_config_keys(self, composition, default=[]):
        return get_value_or(self.config, "compositions/config_keys/excluded/{}".format(composition), default)


    def filtered_output_keys(self, composition, default=[]):
        return get_value_or(self.config, "compositions/config_keys/filtered/{}".format(composition), default)


    def terraform_composition_order(self, default=[]):
        return self.composition_order("terraform")


    def helmfile_composition_order(self, default=[]):
        return self.composition_order("helmfile")


    def composition_order(self, composition, default=[]):
        return get_value_or(self.config, "compositions/order/{}".format(composition), default)


    def terraform_version(self):
        return get_value_or(self.config, "terraform/version", 'latest')


    def terraform_repo_url(self):
        return self.config['terraform']['repo']['url']


    def terraform_repo_name(self):
        return self.config['terraform']['repo']['name']


    def terraform_root_path(self):
        return self.config['terraform']['root_path']


    def terraform_local_path(self):
        return os.path.expanduser(self.config['terraform']['local_path'])


    def helmfile_repo_url(self):
        return self.config['helmfile']['repo']['url']


    def helmfile_repo_name(self):
        return self.config['helmfile']['repo']['name']


    def helmfile_root_path(self):
        return self.config['helmfile']['root_path']


    def helmfile_local_path(self):
        return os.path.expanduser(self.config['helmfile']['local_path'])
