# Copyright 2026 Adobe. All rights reserved.
# This file is licensed to you under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License. You may obtain a copy
# of the License at http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software distributed under
# the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR REPRESENTATIONS
# OF ANY KIND, either express or implied. See the License for the specific language
# governing permissions and limitations under the License.

import logging
import os

from kompos.parser import SubParserConfig
from kompos.runners.terraform_helper import GenericTerraformRunner

logger = logging.getLogger(__name__)  

RUNNER_TYPE = "terraform"


class TerraformParser(SubParserConfig):
    def get_name(self):
        return RUNNER_TYPE

    def get_help(self):
        return 'Wrap common terraform tasks with full templated configuration support'

    def configure(self, parser):
        """Add terraform-specific arguments."""
        parser.add_argument('subcommand', help='One of the terraform commands', type=str)
        parser.add_argument('--dry-run', action='store_true',
                            help='Generate all files but do not execute terraform command')
        return parser

    def get_epilog(self):
        return '''
        Examples:
            # Run terraform plan
            kompos data/env=dev/region=va6/project=ee/cluster=experiments/composition=terraform terraform plan 
            # Run terraform apply on a specific composition
            kompos data/env=dev/region=va6/project=ee/cluster=experiments/composition=terraform/terraform=mycomposition terraform apply
        '''


class TerraformRunner(GenericTerraformRunner):
    """
    Local Terraform execution runner.
    
    Executes Terraform commands locally after generating configuration files.
    Uses temporary runtime directories for execution.
    """

    # Terraform subcommands that will need re-initialization
    SUBCMDS_WITH_INIT = ('plan', 'apply', 'destroy', 'import', 'state')

    # Terraform subcommands that use the variables file
    SUBCMDS_WITH_VARS = ('plan', 'apply', 'destroy', 'import')

    # Subcommand that reverses composition order
    REVERSE_COMPOSITION_CMD = 'destroy'

    # File naming conventions
    VERSIONED_EXTENSION = '.tf.versioned'
    CONFIG_FILENAME = 'variables.tfvars.json'
    CACHE_DIR = '~/.kompos/.terraform.d/plugin-cache'

    def __init__(self, kompos_config, config_path, execute):
        super(TerraformRunner, self).__init__(kompos_config, config_path, execute, RUNNER_TYPE)

    def run_configuration(self, args):
        self.ordered_compositions = True
        self.reverse = (self.REVERSE_COMPOSITION_CMD == args.subcommand)

    def execution_configuration(self, composition, config_path, default_output_path, raw_config,
                                filtered_keys, excluded_keys):
        # Source composition path
        source_composition_path = self.get_source_composition_path(composition, raw_config)

        # Runtime directory path (where we generate and execute)
        runtime_dir = self.get_runtime_dir(
            default_output_path,
            raw_config['cloud']['provider'],
            composition
        )

        # Clean and recreate runtime directory to ensure fresh state
        self.ensure_directory(runtime_dir, clean=True)
        logger.info(f'Using runtime directory: {runtime_dir}')

        # Note: provider.tf should use native TF variables, not generated from Hiera

        # Generate variables.tfvars.json
        variables_path = os.path.join(runtime_dir, self.CONFIG_FILENAME)
        self.generate_terraform_config(
            target_file=variables_path,
            config_path=config_path,
            filtered_keys=filtered_keys,
            excluded_keys=excluded_keys + self.TERRAFORM_SYSTEM_KEYS,
            output_format='json',
            enclosing_key='config',
            print_data=True
        )

        # Process composition files (versioned + static)
        if self.is_versioned_module_sources_enabled():
            self.process_composition_files(source_composition_path, runtime_dir, raw_config)

    @staticmethod
    def execution(args, extra_args, default_output_path, composition, raw_config):
        # Runtime directory for TF execution
        runtime_dir = os.path.join(default_output_path, raw_config['cloud']['provider'], composition)

        # Handle dry-run mode: skip terraform execution
        if args.dry_run:
            logger.info(f'DRY-RUN: Skipping terraform execution for composition: {composition}')
            logger.info(f'DRY-RUN: Generated files are in: {runtime_dir}')
            # Return a no-op command that always succeeds
            return dict(command="echo 'Dry-run mode: skipping terraform execution'")

        var_file = f'-var-file="{TerraformRunner.CONFIG_FILENAME}"' if args.subcommand in TerraformRunner.SUBCMDS_WITH_VARS else ''
        terraform_env_config = f'export TF_PLUGIN_CACHE_DIR="{TerraformRunner.local_config_dir()}"'

        remove_cache = TerraformRunner.remove_local_cache_cmd(args.subcommand)
        extra_args_str = ' '.join(extra_args)
        cmd = (f"cd {runtime_dir} && "
               f"{remove_cache} "
               f"{terraform_env_config} ; terraform init && terraform {args.subcommand} {var_file} {extra_args_str}")

        return dict(command=cmd)

    @staticmethod
    def remove_local_cache_cmd(subcommand):
        """Generate command to remove local .terraform cache if needed."""
        if subcommand in TerraformRunner.SUBCMDS_WITH_INIT:
            return 'rm -rf .terraform &&'
        return ''

    @staticmethod
    def local_config_dir(directory=None):
        """
        Create and return path to Terraform plugin cache directory.
        
        Args:
            directory: Optional cache directory path (default: TerraformRunner.CACHE_DIR)
            
        Returns:
            str: Expanded path to cache directory
        """
        if directory is None:
            directory = TerraformRunner.CACHE_DIR

        try:
            expanded_path = os.path.expanduser(directory)
            os.makedirs(expanded_path, exist_ok=True)
            return expanded_path
        except IOError:
            logging.error(f"Failed to create dir in path: {directory}")
