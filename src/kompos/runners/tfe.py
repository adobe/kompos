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
from kompos.runner import GenericRunner

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
        parser.add_argument('--output-dir',
                            type=str,
                            help='Base output directory (default from .komposconfig.yaml or ./rendered)')

        # Add all HIML arguments (filter, exclude, skip-secrets, etc.)
        ConfigRunner().get_parser(parser)

        return parser

    def get_epilog(self):
        return '''
        Examples:
        # Generate both tfvars and workspace config
        kompos data/cloud=aws/project=aip-training/env=dev/region=or2/cluster=sloth/composition=cluster tfe generate
        
        # Only tfvars with filters
        kompos data/.../cluster=sloth/... tfe generate --tfvars-only --filter cluster --exclude terraform
        
        # Custom output directory
        kompos data/.../cluster=sloth/... tfe generate --output-dir ./my-rendered
        '''


class TFERunner(GenericRunner):
    def __init__(self, kompos_config, full_config_path, config_path, execute):
        super(TFERunner, self).__init__(kompos_config, full_config_path, config_path, execute, RUNNER_TYPE)

    def run_configuration(self, args):
        self.validate_runner = False
        self.ordered_compositions = False
        self.reverse = False
        self.generate_output = False

    def validate_config(self, raw_config):
        """Validate required TFE configuration exists"""
        if 'tfe' not in raw_config:
            logger.error("Missing 'tfe' config in hierarchy. Add to your defaults.")
            return False
        return True

    def execution_configuration(self, composition, config_path, default_output_path, raw_config,
                                filtered_keys, excluded_keys):
        args = self.himl_args

        # Validate config early
        if not self.validate_config(raw_config):
            return

        # Determine what to generate
        generate_tfvars = not args.workspace_only
        generate_workspace = not args.tfvars_only

        # Generate tfvars file
        if generate_tfvars:
            self.generate_tfvars(config_path, raw_config, filtered_keys, excluded_keys)

        # Generate workspace config file
        if generate_workspace:
            self.generate_workspace_config(config_path, raw_config)

    def generate_tfvars(self, config_path, raw_config, filtered_keys, excluded_keys):
        """Generate the tfvars YAML file for TFE"""
        # Get TFE tfvars configuration from hiera
        tfvars_config = raw_config.get('tfe', {}).get('tfvars', {})
        if not tfvars_config:
            logger.error("No 'tfe.tfvars' configuration found in hierarchy")
            return

        # Extract config
        output_dir = tfvars_config.get('output_dir', './rendered/clusters')
        filename = tfvars_config.get('filename', '{cluster}')
        output_format = tfvars_config.get('format', 'yaml')

        # Build output path
        extension = 'yaml' if output_format == 'yaml' else 'json'
        output_file = os.path.join(output_dir, f"{filename}.tfvars.{extension}")

        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_file), exist_ok=True)

        logger.info('Generating TFE tfvars file: %s', output_file)

        # Generate the config
        # Default: enclosing_key="config", exclude terraform/composition
        self.generate_config(
            config_path=config_path,
            filters=filtered_keys,
            exclude_keys=excluded_keys + ['terraform', 'composition'],
            enclosing_key='config',
            output_format=output_format,
            output_file=output_file,
            print_data=False,
            skip_interpolation_resolving=self.himl_args.skip_interpolation_resolving,
            skip_interpolation_validation=self.himl_args.skip_interpolation_validation,
            skip_secrets=self.himl_args.skip_secrets,
            multi_line_string=True
        )

        logger.info('✓ Generated tfvars: %s', output_file)

    def generate_workspace_config(self, config_path, raw_config):
        """Generate the workspace configuration file for TFE workspace creation"""
        # Get TFE workspace configuration from hiera
        workspace_config = raw_config.get('tfe', {}).get('workspace', {})
        if not workspace_config:
            logger.error("No 'tfe.workspace' configuration found in hierarchy")
            return

        # Extract config
        output_dir = workspace_config.get('output_dir', './rendered/workspaces')
        filename = workspace_config.get('filename', '{cluster}')
        output_format = workspace_config.get('format', 'yaml')

        # Build output path
        extension = 'yaml' if output_format == 'yaml' else 'json'
        output_file = os.path.join(output_dir, f"{filename}.workspace.{extension}")

        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_file), exist_ok=True)

        logger.info('Generating TFE workspace config: %s', output_file)

        # Use generate_config to write workspace data from hiera
        # The workspace structure should be defined in hiera under tfe.workspace
        self.generate_config(
            config_path=config_path,
            filters=['tfe.workspace'],
            exclude_keys=['output_dir', 'filename', 'format'],  # Exclude metadata
            output_format=output_format,
            output_file=output_file,
            print_data=False,
            skip_interpolation_resolving=self.himl_args.skip_interpolation_resolving,
            skip_interpolation_validation=self.himl_args.skip_interpolation_validation,
            skip_secrets=self.himl_args.skip_secrets
        )

        logger.info('✓ Generated workspace config: %s', output_file)

    @staticmethod
    def execution(args, extra_args, default_output_path, composition, raw_config):
        """No actual execution needed - files are generated in execution_configuration"""
        cmd = ""
        return dict(command=cmd)
