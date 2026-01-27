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
import shutil

from kompos.parser import SubParserConfig
from kompos.runner import GenericRunner
from kompos.helpers.terraform_helper import TerraformVersionedSourceProcessor

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
# File naming conventions
TERRAFORM_VERSIONED_EXTENSION = ".tf.versioned"  # For module source version interpolation
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
        parser.add_argument('--dry-run', action='store_true', 
                          help='Generate all files but do not execute terraform command')

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
    def __init__(self, kompos_config, config_path, execute):
        super(TerraformRunner, self).__init__(kompos_config, config_path, execute, RUNNER_TYPE)
        
        # Initialize versioned source processor
        self.versioned_processor = TerraformVersionedSourceProcessor(TERRAFORM_VERSIONED_EXTENSION)

    def run_configuration(self, args):
        self.ordered_compositions = True
        self.reverse = (RUNNER_REVERSE_COMPOSITION_CMD == args.subcommand)

    def execution_configuration(self, composition, config_path, default_output_path, raw_config,
                                filtered_keys, excluded_keys):
        # Source composition path (where .tf and .tf.versioned files are)
        source_composition_path = os.path.join(
            self.kompos_config.local_path(RUNNER_TYPE),
            self.kompos_config.root_path(RUNNER_TYPE),
            raw_config["cloud"]["type"],
            composition
        )
        
        # Runtime directory path (where we generate and execute)
        runtime_dir = os.path.join(default_output_path, raw_config["cloud"]["type"], composition)
        
        # Clean and recreate runtime directory to ensure fresh state
        if os.path.exists(runtime_dir):
            logger.debug('Cleaning runtime directory: %s', runtime_dir)
            shutil.rmtree(runtime_dir)
        
        os.makedirs(runtime_dir, exist_ok=True)
        logger.info('Using runtime directory: %s', runtime_dir)
        
        # Copy source .tf files (excluding .tf.versioned) to runtime directory
        self._copy_source_files(source_composition_path, runtime_dir)
        
        # Generate provider with subpath for cloud specific modules
        # .kompos-runtime/terraform/aws/vpc/provider.tf.json
        provider_path = os.path.join(runtime_dir, TERRAFORM_PROVIDER_FILENAME)
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
        variables_path = os.path.join(runtime_dir, TERRAFORM_CONFIG_FILENAME)
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
        
        # Process versioned module sources if enabled
        if self.kompos_config.terraform_versioned_module_sources_enabled():
            self.versioned_processor.process(source_composition_path, runtime_dir, raw_config)
    
    def _copy_source_files(self, source_dir, target_dir):
        """
        Copy source .tf files (excluding .tf.versioned templates) to runtime directory.
        
        This allows Terraform to run with all necessary files in the runtime location
        while keeping generated files separate from source files.
        """
        if not os.path.exists(source_dir):
            logger.warning('Source composition directory does not exist: %s', source_dir)
            return
        
        for filename in os.listdir(source_dir):
            # Copy .tf files (but not .tf.versioned templates)
            if filename.endswith('.tf') and not filename.endswith('.tf.versioned'):
                source_file = os.path.join(source_dir, filename)
                target_file = os.path.join(target_dir, filename)
                
                if os.path.isfile(source_file):
                    shutil.copy2(source_file, target_file)
                    logger.debug('Copied %s to runtime directory', filename)

    @staticmethod
    def execution(args, extra_args, default_output_path, composition, raw_config):
        # Handle dry-run mode: skip terraform execution
        if args.dry_run:
            runtime_dir = os.path.join(default_output_path, raw_config["cloud"]["type"], composition)
            logger.info("DRY-RUN: Skipping terraform execution for composition: %s", composition)
            logger.info("DRY-RUN: Generated files are in: %s", runtime_dir)
            # Return a no-op command that always succeeds
            return dict(command="echo 'Dry-run mode: skipping terraform execution'")
        
        # Runtime directory for TF execution
        runtime_dir = os.path.join(default_output_path, raw_config["cloud"]["type"], composition)
        var_file = '-var-file="{}"'.format(TERRAFORM_CONFIG_FILENAME) if args.subcommand in SUBCMDS_WITH_VARS else ''
        terraform_env_config = 'export TF_PLUGIN_CACHE_DIR="{}"'.format(local_config_dir())

        cmd = "cd {terraform_path} && " \
              "{remove_local_cache} " \
              "{env_config} ; terraform init && terraform {subcommand} {var_file} {extra_args}".format(
            terraform_path=runtime_dir,
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
