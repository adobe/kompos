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
        '''


class TFERunner(GenericRunner):
    def __init__(self, kompos_config, config_path, execute):
        super(TFERunner, self).__init__(kompos_config, config_path, execute, RUNNER_TYPE)

    def run_configuration(self, args):
        self.validate_runner = False
        self.ordered_compositions = False
        self.reverse = False
        self.generate_output = False

    def _get_workspace_name(self, raw_config):
        """Extract workspace name from workspaces list in hiera"""
        workspaces = raw_config.get('workspaces', [])
        if not workspaces or not isinstance(workspaces, list):
            logger.warning("No 'workspaces' list found in hierarchy")
            return None
        return workspaces[0].get('name', 'cluster')

    def _get_tfe_config(self, key, default=None):
        """Get TFE configuration value with default fallback"""
        return self.kompos_config.get('tfe', {}).get(key, default)

    def _build_output_path(self, base_dir, subdir_key, raw_config, fallback_name, filename):
        """Build output path with optional subdirectory based on config key"""
        output_dir = base_dir
        
        # Optionally create cluster-specific subdirectory if key is configured
        if subdir_key:
            subdir_name = self.get_nested_value(raw_config, subdir_key)
            if not subdir_name:
                logger.warning("Could not resolve '%s', falling back to: %s", subdir_key, fallback_name)
                subdir_name = fallback_name
            output_dir = os.path.join(output_dir, subdir_name)
        
        return os.path.join(output_dir, filename)

    def _ensure_output_dir(self, file_path):
        """Ensure the directory for the output file exists"""
        output_dir = os.path.dirname(file_path)
        os.makedirs(output_dir, exist_ok=True)

    def execution_configuration(self, composition, config_path, default_output_path, raw_config,
                                filtered_keys, excluded_keys):
        args = self.himl_args

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
        """Generate the tfvars file for TFE"""
        workspace_name = self._get_workspace_name(raw_config)
        if not workspace_name:
            return

        # Get output configuration
        clusters_base_dir = self._get_tfe_config('clusters_dir', './rendered/clusters')
        clusters_subdir_key = self._get_tfe_config('clusters_subdir_key')
        tfvars_format = self._get_tfe_config('tfvars_format', 'yaml')
        tfvars_extension = self._get_tfe_config('tfvars_extension', '.tfvars.yaml')
        
        # Build output path
        output_file = self._build_output_path(
            base_dir=clusters_base_dir,
            subdir_key=clusters_subdir_key,
            raw_config=raw_config,
            fallback_name=workspace_name,
            filename=f"cluster{tfvars_extension}"
        )

        # Ensure output directory exists
        self._ensure_output_dir(output_file)

        logger.info('Generating TFE tfvars file: %s', output_file)

        # Generate the config - exclude metadata keys
        self.generate_config(
            config_path=config_path,
            filters=filtered_keys,
            exclude_keys=excluded_keys + ['terraform', 'composition', 'workspaces'],
            enclosing_key='config',
            output_format=tfvars_format,
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
        workspace_name = self._get_workspace_name(raw_config)
        if not workspace_name:
            return

        # Get output configuration
        output_dir = self._get_tfe_config('workspaces_dir', './rendered/workspaces')
        workspace_format = self._get_tfe_config('workspace_format', 'yaml')
        workspace_extension = self._get_tfe_config('workspace_extension', '.workspace.yaml')
        output_file = os.path.join(output_dir, f"{workspace_name}{workspace_extension}")

        # Ensure output directory exists
        self._ensure_output_dir(output_file)

        logger.info('Generating TFE workspace config: %s', output_file)

        # Filter to workspaces and output as-is (keep the workspaces: key)
        self.generate_config(
            config_path=config_path,
            filters=['workspaces'],
            output_format=workspace_format,
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
