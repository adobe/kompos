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
import time

from kompos.parser import SubParserConfig
from kompos.runners.terraform_helper import GenericTerraformRunner
from kompos.helpers import console

logger = logging.getLogger(__name__)

RUNNER_TYPE = "tfe"


class TFEParserConfig(SubParserConfig):
    def get_name(self):
        return RUNNER_TYPE

    def get_help(self):
        return 'Generate Terraform Enterprise (TFE) workspace and tfvars configurations'

    def configure(self, parser):
        """Add TFE-specific arguments and standard HIML arguments."""
        # TFE subcommand
        parser.add_argument('subcommand',
                            metavar='SUBCOMMAND',
                            choices=['generate'],
                            help='Action to perform: generate')

        # TFE-specific options
        parser.add_argument('--tfvars-only',
                            action='store_true',
                            help='Generate only tfvars file (skip workspace config)')
        parser.add_argument('--workspace-only',
                            action='store_true',
                            help='Generate only workspace config (skip tfvars)')

        # Add HIML arguments
        self.add_himl_arguments(parser)
        return parser

    def get_epilog(self):
        return '''
Examples:
  # Generate TFE workspace and tfvars for an account composition
  kompos configs/cloud=aws/project=demo/env=dev/composition=account tfe generate
  
  # Generate for a cluster composition
  kompos configs/cloud=aws/project=demo/env=dev/region=us-west-2/cluster=demo01/composition=cluster tfe generate
  
  # Generate only tfvars (skip workspace config)
  kompos configs/.../composition=cluster tfe generate --tfvars-only
  
  # Generate with custom filters
  kompos configs/.../composition=cluster tfe generate --filter cluster --filter vpc --exclude node_groups

Output:
  - Composition files: generated/{composition_type}/{instance}/
  - Workspace config:  generated/workspaces/{instance}.workspace.yaml
  - Tfvars file:       generated/{composition_type}/{instance}/generated.tfvars.yaml

For more information, see: docs/GUIDE.md
        '''


class TFERunner(GenericTerraformRunner):
    def __init__(self, kompos_config, config_path, execute):
        super(TFERunner, self).__init__(kompos_config, config_path, execute, RUNNER_TYPE)

        # Cache TFE-specific configuration from .komposconfig.yaml for performance
        # base_dir and use_composition_output_dir are inherited from GenericTerraformRunner
        
        # Generation config
        self.generate_compositions = self.kompos_config.get_runtime_setting(
            self.runner_type, 'generation_config.generate_compositions', True)

        # Workspace configuration
        workspace_config = self.kompos_config.get_runtime_setting(
            self.runner_type, 'workspaces_config', {})
        
        self.generate_workspaces = workspace_config.get('generate', True)
        self.workspace_config_key = workspace_config.get('config_key', 'workspace')
        
        # Build workspaces directory from base + subdir
        base_output_dir = self.kompos_config.get_runtime_setting(
            self.runner_type, 'generation_config.base_output_dir', './generated')
        workspaces_subdir = workspace_config.get('workspaces_sub_dir', 'workspaces')
        self.workspaces_dir = os.path.join(base_output_dir, workspaces_subdir)
        
        self.workspace_extension = workspace_config.get('workspace_extension', '.workspace.yaml')
        self.workspace_format = self.extract_format_from_extension(self.workspace_extension)

        # Tfvars configuration
        tfvars_config = self.kompos_config.get_runtime_setting(
            self.runner_type, 'tfvars_config', {})
        
        self.tfvars_extension = tfvars_config.get('extension', '.tfvars.yaml')
        self.tfvars_format = self.extract_format_from_extension(self.tfvars_extension)
        
        # If tfvars_filename is None/not set, will use composition name (backward compatible)
        # If set to a string like "generated", will use that instead
        self.tfvars_filename = tfvars_config.get('filename', None)

    def run_configuration(self, args):
        self.validate_runner = False
        self.ordered_compositions = False
        self.reverse = False
        self.generate_output = False

    def execution_configuration(self, composition, config_path, default_output_path, raw_config,
                                filtered_keys, excluded_keys):
        args = self.himl_args
        
        # Start timing
        start_time = time.time()
        composition_files = 0
        config_files = 0

        # Determine what to generate
        generate_tfvars = not args.workspace_only
        generate_workspace = not args.tfvars_only and self.generate_workspaces
        generate_composition = self.generate_compositions

        # Generate per-cluster composition (working_directory for TFE)
        if generate_composition:
            file_count = self.generate_composition(composition, raw_config)
            composition_files = file_count if file_count else 0
            # Add separator after composition files if we're generating config files
            if generate_tfvars or generate_workspace:
                print()

        # Generate tfvars file
        if generate_tfvars:
            self.generate_tfvars(composition, config_path, raw_config, filtered_keys, excluded_keys)
            config_files += 1

        # Generate workspace config file
        if generate_workspace:
            self.generate_workspace_config(config_path, raw_config)
            config_files += 1
        
        # Print summary with metrics
        total_files = composition_files + config_files
        elapsed_time = time.time() - start_time
        console.print_summary(total_files=total_files, elapsed_time=elapsed_time)

    def generate_composition(self, composition, raw_config):
        """
        Generate per-cluster TFE working_directory with modules.
        
        Processes .tf.versioned files and copies static .tf files.
        Note: Provider config should use native TF variables, not generated from Hiera.
        
        Args:
            composition: Name of the composition (e.g., 'cluster')
            raw_config: Configuration dictionary from hiera
            
        Returns:
            int: Total number of files processed
        """
        cluster_name = self.get_composition_name(raw_config)
        if not cluster_name:
            return 0

        # Source composition path
        source_composition_path = self.get_source_composition_path(composition, raw_config)

        if not os.path.exists(source_composition_path):
            raise FileNotFoundError(
                f'Source composition directory does not exist: {source_composition_path}\n'
                f'Composition: {composition}, Cloud provider: {raw_config["cloud"]["provider"]}'
            )

        # Target composition path: base/composition_type/composition_instance
        # - base: ./generated (from .komposconfig.yaml defaults.base_dir)
        # - composition_type: accounts/ or clusters/ (from .komposconfig.yaml properties)
        # - composition_instance: my-account/ (from composition.output_dir interpolation)
        composition_output_dir = self.kompos_config.get_composition_output_dir(self.base_dir, composition)
        instance_dir = self.get_composition_output_dir(raw_config)
        target_dir = self.build_output_path(
            base_dir=composition_output_dir,
            name=instance_dir,
            use_subdir=self.use_composition_subdir
        )

        self.ensure_directory(target_dir)

        console.print_composition_header(
            composition_name=cluster_name,
            composition_type=composition,
            source=source_composition_path,
            target=target_dir,
            config_path=self.config_path
        )

        # Process all composition files (versioned + static)
        # Note: provider.tf should use native TF variables, not generated from Hiera
        file_count = 0
        if self.is_versioned_module_sources_enabled():
            processed, copied = self.process_composition_files(source_composition_path, target_dir, raw_config)
            file_count = processed + copied

        print()  # Blank line for spacing
        console.print_success(f"Composition files copied ({file_count} files)")
        
        return file_count

    def generate_tfvars(self, composition, config_path, raw_config, filtered_keys, excluded_keys):
        """Generate the tfvars file for TFE (per-composition)"""
        workspace_name = self.get_composition_name(raw_config)
        if not workspace_name:
            return

        # Determine base filename: use configured name OR composition name for backward compatibility
        base_filename = self.tfvars_filename if self.tfvars_filename else workspace_name
        tfvars_filename = f'{base_filename}{self.tfvars_extension}'

        # Build output path: base/composition_type/composition_instance/filename
        composition_output_dir = self.kompos_config.get_composition_output_dir(self.base_dir, composition)
        instance_dir = self.get_composition_output_dir(raw_config)
        output_file = self.build_output_path(
            base_dir=composition_output_dir,
            name=instance_dir,
            filename=tfvars_filename,
            use_subdir=self.use_composition_subdir
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
        
        print()  # Blank line for spacing
        console.print_success("Configuration generated")
        console.print_file_generation("tfvars", output_file)

    def generate_workspace_config(self, config_path, raw_config):
        """Generate the workspace configuration file for TFE workspace creation"""
        workspace_name = self.get_composition_name(raw_config)
        if not workspace_name:
            return

        # Build output file path
        output_file = self.build_output_path(
            base_dir=self.workspaces_dir,
            filename=f'{workspace_name}{self.workspace_extension}'
        )

        # Ensure output directory exists
        self.ensure_directory(output_file, is_file_path=True)

        # Filter to workspace key (config_key from .komposconfig.yaml)
        self.generate_terraform_config(
            target_file=output_file,
            config_path=config_path,
            filtered_keys=[self.workspace_config_key],
            output_format=self.workspace_format,
            print_data=False
        )
        
        console.print_file_generation("workspace", output_file)

    @staticmethod
    def execution(args, extra_args, default_output_path, composition, raw_config):
        """No actual execution needed - files are generated in execution_configuration"""
        cmd = ""
        return dict(command=cmd)
