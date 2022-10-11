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
from pathlib import Path

from kompos.parser import SubParserConfig
from kompos.runner import GenericRunner

logger = logging.getLogger(__name__)

# Terraform subcommands that will need re-initialization
SUBCMDS_WITH_INIT = [
    'plan',
    'apply',
    'destroy',
    'import',
    'state'
]

# Terraform subcommands that use the variables file.
SUBCMDS_WITH_VARS = [
    'plan',
    'apply',
    'destroy',
    'import'
]

RUNNER_TYPE = "terraform"
RUNNER_REVERSE_COMPOSITION_CMD = "destroy"
# The filename of the generated hierarchical configuration for Terrraform.
TERRAFORM_CONFIG_FILENAME = "variables.tfvars.json"
# The filename of the generated Terrraform provider.
TERRAFORM_PROVIDER_FILENAME = "provider.tf.json"
# Directory to store terraform plugin cache
TERRAFORM_CACHE_DIR = "~/.kompos/.terraform.d/plugin-cache"


class TerraformParser(SubParserConfig):
    def get_name(self):
        return RUNNER_TYPE

    def get_help(self):
        return 'Wrap common terraform tasks with full templated configuration support'

    def configure(self, parser):
        parser.add_argument('subcommand', help='One of the terraform commands', type=str)

        return parser

    def get_epilog(self):
        return '''
        Examples:
            # Run helmfile sync
            kompos data/env=dev/region=va6/project=ee/cluster=experiments/composition=terraform terraform plan 
            # Run helmfile sync on a single composition
            kompos data/env=dev/region=va6/project=ee/cluster=experiments/composition=terraform/terraform=myterraformcomposition terraform plan
        '''


class TerraformRunner(GenericRunner):
    def __init__(self, kompos_config, full_config_path, config_path, execute):
        super(TerraformRunner, self).__init__(kompos_config, full_config_path, config_path, execute, RUNNER_TYPE)

    def run_configuration(self, args):
        self.ordered_compositions = True
        self.reverse = (RUNNER_REVERSE_COMPOSITION_CMD == args.subcommand)

    def execution_configuration(self, composition, config_path, default_output_path, raw_config,
                                filtered_keys, excluded_keys):
        # Generate provider with subpath for cloud specific modules
        # ./terraform/compositions/aws/provider.tf.json
        provider_path = os.path.join(default_output_path, raw_config["cloud"]["type"], composition,
                                     TERRAFORM_PROVIDER_FILENAME)
        logger.info('Generating terraform provider %s', provider_path)
        self.generate_config(
            config_path=config_path,
            exclude_keys=excluded_keys,
            filters=filtered_keys + ["provider", "terraform"],
            output_format="json",
            output_file=provider_path,
            print_data=True,
            skip_interpolation_resolving=self.himl_args.skip_interpolation_resolving,
            skip_interpolation_validation=self.himl_args.skip_interpolation_validation,
            skip_secrets=self.himl_args.skip_secrets
        )

        # Generate variables with subpath for cloud specific modules
        variables_path = os.path.join(default_output_path, raw_config["cloud"]["type"], composition,
                                      TERRAFORM_CONFIG_FILENAME)
        logger.info('Generating terraform variables %s', variables_path)
        self.generate_config(
            config_path=config_path,
            exclude_keys=excluded_keys + ["provider"],
            filters=filtered_keys,
            enclosing_key="config",
            output_format="json",
            output_file=variables_path,
            # output_file=os.path.expanduser(config_path),
            print_data=True,
            skip_interpolation_resolving=self.himl_args.skip_interpolation_resolving,
            skip_interpolation_validation=self.himl_args.skip_interpolation_validation,
            skip_secrets=self.himl_args.skip_secrets
        )

    @staticmethod
    def execution(args, extra_args, default_output_path, composition, raw_config):
        # Add cloud subpath for TF modules
        terraform_composition_path = os.path.join(default_output_path, raw_config["cloud"]["type"], composition)
        var_file = '-var-file="{}"'.format(TERRAFORM_CONFIG_FILENAME) if args.subcommand in SUBCMDS_WITH_VARS else ''
        terraform_env_config = 'export TF_PLUGIN_CACHE_DIR="{}"'.format(local_config_dir())

        cmd = "cd {terraform_path} && " \
              "{remove_local_cache} " \
              "{env_config} ; terraform init && terraform {subcommand} {var_file} {extra_args}".format(
            terraform_path=terraform_composition_path,
            remove_local_cache=remove_local_cache_cmd(args.subcommand),
            subcommand=args.subcommand,
            extra_args=' '.join(extra_args),
            var_file=var_file,
            env_config=terraform_env_config)

        return dict(command=cmd)


def remove_local_cache_cmd(subcommand):
    if subcommand in SUBCMDS_WITH_INIT:
        return 'rm -rf .terraform &&'

    return ''


def local_config_dir(directory=TERRAFORM_CACHE_DIR):
    try:
        Path(Path.expanduser(Path(directory))).mkdir(parents=True, exist_ok=True)
        return Path.expanduser(Path(directory))

    except IOError:
        logging.error("Failed to create dir in path: %s", directory)
