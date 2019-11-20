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

from functools import reduce


logger = logging.getLogger(__name__)


# The filename of the generated hierarchical configuration for Terrraform.
TERRAFORM_CONFIG_FILENAME = "variables.tfvars.json"

# The filename of the generated Terrraform provider.
TERRAFORM_PROVIDER_FILENAME = "provider.tf.json"

# The filename of the generated hierarchical configuration for Helmfile.
HELMFILE_CONFIG_FILENAME = "hiera-generated.yaml"


def get_value_or(dictionary, x_path, default=None):
    """
    Try to retrieve a value from a dictionary. Return the default if no such value is found.
    """
    keys = x_path.split("/")
    return reduce(
        lambda d, key: d.get(key, default)
        if isinstance(d, dict) else default, keys, dictionary)


def file_tree(config_path, search_fname):
    """ From the current dir returns a list with all the files in the file tree to the root dir """

    parts = os.path.realpath(config_path)

    file_stack = []

    while parts:
        fname = '/'.join((parts, search_fname))
        file_stack.append(fname)
        parts = parts.rpartition('/')[0]

    return file_stack


def read_value_from_file(file, extract_function):
    with open(file, 'r') as f:
        return extract_function(yaml.loads(f.read()))


class KomposConfig(object):
    """
    Parses the all .komposconfig.yaml files that it can find starting from the
    first down the path to the one in the current dir

    For /root/cluster/cluster.yaml:

        /etc/kompos/.komposconfig.yaml
        ~/.komposconfig.yaml
        /root/.komposconfig.yaml
        /root/cluster/.komposconfig.yaml
    """

    DEFAULTS = {
        # cache dir
        'cache.dir': '~/.kompos/cache',

        # terraform options
        'terraform.version': 'latest',

        # S3 remote state
        'terraform.s3_state': False,

        # Integrate https://github.com/coinbase/terraform-landscape
        'terraform.landscape': False,

        # Remove .terraform folder before each terraform plan, to prevent reuse of installed backends (it can confuse terraform when the cluster backend is
        # not the same for all of them)
        'terraform.remove_local_cache': False,
    }

    DEFAULT_PATHS = [
        '/etc/kompos/.komposconfig.yaml',
        '~/.komposconfig.yaml'
    ]

    def __init__(self, console_args, package_dir):
        cluster_config_path = console_args.cluster_config_path
        self.config = self.DEFAULTS
        self.package_dir = package_dir

        paths = self.DEFAULT_PATHS[:]
        for fname in reversed(
                file_tree(cluster_config_path, '.komposconfig.yaml')):
            if fname not in paths:
                paths.append(fname)

        parsed_files = []
        logger.debug("parsing %s", paths)

        for config_path in paths:
            config_path = os.path.realpath(os.path.expanduser(config_path))
            if os.path.isfile(config_path):
                logger.info("parsing %s", config_path)
                with open(config_path) as f:
                    config = yaml.safe_load(f.read())
                    if isinstance(config, dict):
                        parsed_files.append(config_path)
                        self.config.update(config)
                    else:
                        logger.error(
                            "cannot parse yaml dict from file: %s", config_path)

        self.parsed_files = parsed_files
        logger.info("final kompos config: %s from %s", self.config, parsed_files)

    def get(self, item, default=None):
        return self.config.get(item, default)

    @property
    def terraform_config_path(self):
        default_path = self.package_dir + '/data/terraform/terraformrc'
        return self.config.get('terraform.config_path', default_path)

    def __contains__(self, item):
        return item in self.config

    def __getitem__(self, item):
        if item not in self.config:
            raise KeyError("%s not found in %s" % (item, self.parsed_files))

        return self.config[item]

    def all(self):
        return self.config


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


    def terraform_remove_local_cache(self):
        return get_value_or(self.config, "terraform/remove_local_cache", False)


    def terraform_version(self):
        return get_value_or(self.config, "terraform/version", 'latest')


    def terraform_repo_url(self):
        return self.config['terraform']['repo_url']


    def terraform_repo_name(self):
        return self.config['terraform']['repo_name']


    def terraform_root_path(self):
        return self.config['terraform']['root_path']


    def terraform_local_path(self):
        return self.config['terraform']['local_path']


    def helmfile_repo_url(self):
        return self.config['helmfile']['repo_url']


    def helmfile_repo_name(self):
        return self.config['helmfile']['repo_name']


    def helmfile_root_path(self):
        return self.config['helmfile']['root_path']


    def helmfile_local_path(self):
        return self.config['helmfile']['local_path']
