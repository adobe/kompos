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

from himl import ConfigRunner

from kompos.parser import SubParserConfig
from kompos.runners.terraform_helper import GenericTerraformRunner

logger = logging.getLogger(__name__)

RUNNER_TYPE = "tfe"


class TFEParserConfig(SubParserConfig):
    def get_name(self):
        return RUNNER_TYPE

    def get_help(self):
        return 'Generate configurations for Terraform Enterprise (TFE) with automatic file naming'

    def configure(self, parser):
        # TFE subcommand
        parser.add_argument('subcommand',
                            choices=['generate'],
                            help='TFE subcommand (currently only "generate" is supported)')

        # TFE-specific options
        parser.add_argument('--tfvars-only',
                            action='store_true',
                            help='Generate only tfvars file (skip workspace config)')
        parser.add_argument('--workspace-only',
                            action='store_true',
                            help='Generate only workspace config (skip tfvars)')

        # Add all HIML arguments (filter, exclude, skip-secrets, etc.)
        ConfigRunner().get_parser(parser)

        return parser

    def get_epilog(self):
        return '''
        Examples:
        # Generate both tfvars and workspace config
        kompos data/cloud=aws/project=demo/env=dev/region=us-west-2/cluster=demo-cluster-01/composition=cluster tfe generate
        
        # Only tfvars with filters
        kompos data/.../cluster=demo-cluster-01/... tfe generate --tfvars-only --filter cluster --exclude terraform
        '''


class TFERunner(GenericTerraformRunner):
    def __init__(self, kompos_config, config_path, execute):
        super(TFERunner, self).__init__(kompos_config, config_path, execute, RUNNER_TYPE)
        
        # Cache TFE-specific configuration for performance and cleaner code
        self.use_cluster_subdir = self.get_runner_config('use_cluster_subdir', True)
        
        # Output directories
        self.compositions_dir = self.get_runner_config('compositions_dir', './generated/compositions')
        self.clusters_dir = self.get_runner_config('clusters_dir', './generated/clusters')
        self.workspaces_dir = self.get_runner_config('workspaces_dir', './generated/workspaces')
        
        # Tfvars configuration
        self.tfvars_format = self.get_runner_config('tfvars_format', 'yaml')
        self.tfvars_extension = self.get_runner_config('tfvars_extension', '.tfvars.yaml')
        # If tfvars_filename is None/not set, will use cluster name (backward compatible)
        # If set to a string like "terraform", will use that instead
        self.tfvars_filename = self.get_runner_config('tfvars_filename', None) 
        
        # Workspace configuration
        self.workspace_format = self.get_runner_config('workspace_format', 'yaml')
        self.workspace_extension = self.get_runner_config('workspace_extension', '.workspace.yaml')

    def run_configuration(self, args):
        self.validate_runner = False
        self.ordered_compositions = False
        self.reverse = False
        self.generate_output = False

    def execution_configuration(self, composition, config_path, default_output_path, raw_config,
                                filtered_keys, excluded_keys):
        args = self.himl_args

        # Determine what to generate
        generate_tfvars = not args.workspace_only
        generate_workspace = not args.tfvars_only
        generate_composition = self.get_runner_config('generate_compositions', False)

        # Generate per-cluster composition (working_directory for TFE)
        if generate_composition:
            self.generate_composition(composition, raw_config)

        # Generate tfvars file
        if generate_tfvars:
            self.generate_tfvars(config_path, raw_config, filtered_keys, excluded_keys)

        # Generate workspace config file
        if generate_workspace:
            self.generate_workspace_config(config_path, raw_config)

    def generate_composition(self, composition, raw_config):
        """
        Generate per-cluster TFE working_directory with modules.
        
        Processes .tf.versioned files and copies static .tf files.
        Note: Provider config should use native TF variables, not generated from Hiera.
        
        Args:
            composition: Name of the composition (e.g., 'cluster')
            raw_config: Configuration dictionary from hiera
        """
        cluster_name = self.get_hierarchical_name(raw_config)
        if not cluster_name:
            return

        # Source composition path
        source_composition_path = self.get_source_composition_path(composition, raw_config)

        if not os.path.exists(source_composition_path):
            logger.warning('Source composition directory does not exist: %s', source_composition_path)
            return

        # Target composition path using new build_output_path helper
        target_dir = self.build_output_path(
            base_dir=self.compositions_dir,
            name=cluster_name,
            use_subdir=self.use_cluster_subdir
        )

        self.ensure_directory(target_dir)

        logger.info('Generating TFE composition for %s: %s -> %s',
                    cluster_name, source_composition_path, target_dir)

        # Process all composition files (versioned + static)
        # Note: provider.tf should use native TF variables, not generated from Hiera
        if self.is_versioned_module_sources_enabled():
            self.process_composition_files(source_composition_path, target_dir, raw_config)

        logger.info('✓ Generated composition for: %s', cluster_name)

    def generate_tfvars(self, config_path, raw_config, filtered_keys, excluded_keys):
        """Generate the tfvars file for TFE"""
        workspace_name = self.get_hierarchical_name(raw_config)
        if not workspace_name:
            return

        # Determine base filename: use configured name OR cluster name for backward compatibility
        base_filename = self.tfvars_filename if self.tfvars_filename else workspace_name
        tfvars_filename = f'{base_filename}{self.tfvars_extension}'
        
        # Build output path using new helper
        output_file = self.build_output_path(
            base_dir=self.clusters_dir,
            name=workspace_name,
            filename=tfvars_filename,
            use_subdir=self.use_cluster_subdir
        )

        # Ensure output directory exists
        self.ensure_directory(output_file, is_file_path=True)

        self.generate_terraform_config(
            target_file=output_file,
            config_path=config_path,
            filtered_keys=filtered_keys,
            excluded_keys=excluded_keys + self.TFE_SYSTEM_KEYS + self.TERRAFORM_SYSTEM_KEYS,
            output_format=self.tfvars_format,
            enclosing_key='config',
            print_data=False
        )

        logger.info('✓ Generated tfvars: %s', output_file)

    def generate_workspace_config(self, config_path, raw_config):
        """Generate the workspace configuration file for TFE workspace creation"""
        workspace_name = self.get_hierarchical_name(raw_config)
        if not workspace_name:
            return

        # Build output file path
        output_file = self.build_output_path(
            base_dir=self.workspaces_dir,
            filename=f'{workspace_name}{self.workspace_extension}'
        )

        # Ensure output directory exists
        self.ensure_directory(output_file, is_file_path=True)

        logger.info('Generating TFE workspace config: %s', output_file)

        # Filter to workspaces and output as-is (keep the workspaces: key)
        self.generate_terraform_config(
            target_file=output_file,
            config_path=config_path,
            filtered_keys=['workspaces'],
            output_format=self.workspace_format,
            print_data=False
        )

        logger.info('✓ Generated workspace config: %s', output_file)

    @staticmethod
    def execution(args, extra_args, default_output_path, composition, raw_config):
        """No actual execution needed - files are generated in execution_configuration"""
        cmd = ""
        return dict(command=cmd)
