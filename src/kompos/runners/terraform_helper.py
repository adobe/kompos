# Copyright 2026 Adobe. All rights reserved.
# This file is licensed to you under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License. You may obtain a copy
# of the License at http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software distributed under
# the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR REPRESENTATIONS
# OF ANY KIND, either express or implied. See the License for the specific language
# governing permissions and limitations under the License.

"""
Generic Terraform runner base class and helper utilities.

Provides:
- Base class for Terraform and TFE runners
- Module version pinning via .tf.versioned files
- Composition processing (versioned + static files)
"""

import logging
import os
import re
import shutil

from kompos.runner import GenericRunner
from kompos.helpers import console

logger = logging.getLogger(__name__)


class TerraformVersionedSourceProcessor:
    """
    Processes .tf.versioned files with module source version interpolation.
    
    This processor enables per-environment/cluster module version pinning by:
    1. Finding .tf.versioned files in composition directories
    2. Interpolating {{key.path}} placeholders with config values
    3. Generating static .tf files for Terraform to use
    4. Copying other static files as-is
    
    Example:
        main.tf.versioned:
            module "vpc" {
              source = "git::https://github.com/org/repo.git?ref={{vpc.module_version}}"
            }
        
        Config: {"vpc": {"module_version": "v2.0.0"}}
        
        Generates main.tf:
            module "vpc" {
              source = "git::https://github.com/org/repo.git?ref=v2.0.0"
            }
    """
    
    @staticmethod
    def process(source_dir, target_dir, config, versioned_extension=".tf.versioned"):
        """
        Process all terraform files in source directory and generate in target directory.
        
        Single loop through files:
        - .tf.versioned files → process and generate .tf files
        - Other files → copy as-is
        
        Args:
            source_dir: Path to the source composition directory
            target_dir: Path to the runtime directory
            config: Configuration dictionary for value interpolation
            versioned_extension: File extension for versioned terraform files 
                               (default: .tf.versioned, configurable via .komposconfig.yaml)
        
        Returns:
            Tuple of (processed_count, copied_count)
        """
        if not os.path.exists(source_dir):
            logger.warning(f'Source directory does not exist: {source_dir}')
            return 0, 0

        processed_count = 0
        copied_count = 0

        for filename in os.listdir(source_dir):
            source_file = os.path.join(source_dir, filename)

            if os.path.isdir(source_file):
                continue

            # Process .tf.versioned files
            if TerraformVersionedSourceProcessor._is_versioned_file(filename, versioned_extension):
                TerraformVersionedSourceProcessor._process_file(
                    source_file, target_dir, config, versioned_extension)
                processed_count += 1

            # Skip files generated from hiera
            elif TerraformVersionedSourceProcessor._should_skip_file(filename):
                continue

            # Skip .tf files that have a .versioned counterpart
            elif filename.endswith('.tf') and TerraformVersionedSourceProcessor._has_versioned_counterpart(
                    source_dir, filename, versioned_extension):
                logger.debug(f'Skipping {filename} (generated from .versioned)')
                continue

            # Copy everything else
            else:
                TerraformVersionedSourceProcessor._copy_file(source_file, target_dir, filename)
                copied_count += 1

        if processed_count > 0:
            logger.debug('Processed %d versioned file(s)', processed_count)
        if copied_count > 0:
            logger.debug('Copied %d static file(s)', copied_count)
        
        return processed_count, copied_count

    @staticmethod
    def _is_versioned_file(filename, versioned_extension):
        """Check if file is a .tf.versioned template."""
        return filename.endswith(versioned_extension)

    @staticmethod
    def _should_skip_file(filename):
        """
        Check if file should be skipped during processing.
        
        Currently no files are skipped - all .tf files are copied.
        This method exists for future extensibility.
        """
        return False

    @staticmethod
    def _has_versioned_counterpart(source_dir, filename, versioned_extension):
        """Check if a .tf file has a corresponding .tf.versioned file."""
        versioned_file = os.path.join(source_dir, filename.replace('.tf', versioned_extension))
        return os.path.exists(versioned_file)

    @staticmethod
    def _copy_file(source_file, target_dir, filename):
        """Copy a file to target directory."""
        shutil.copy2(source_file, os.path.join(target_dir, filename))
        logger.debug(f'Copied {filename}')

    @staticmethod
    def _process_file(versioned_file, target_dir, config, versioned_extension):
        """
        Process a single .tf.versioned file.
        
        Args:
            versioned_file: Path to the .tf.versioned template file
            target_dir: Directory where the generated .tf file will be written
            config: Configuration dictionary for value interpolation
            versioned_extension: The extension to replace (e.g., '.tf.versioned')
        """
        # Read the versioned file
        with open(versioned_file, 'r') as f:
            content = f.read()

        # Interpolate {{key.path}} placeholders and get interpolation info
        interpolated_content, interpolations = TerraformVersionedSourceProcessor.interpolate_sources(content, config)

        # Write to .tf file (remove .versioned extension) in target directory
        output_filename = os.path.basename(versioned_file).replace(versioned_extension, '.tf')
        output_file = os.path.join(target_dir, output_filename)

        with open(output_file, 'w') as f:
            f.write(interpolated_content)

        # Display interpolations to user
        if interpolations:
            for placeholder, value in interpolations:
                # Extract module name from placeholder (e.g., "vpc.module_version" -> "vpc")
                module_name = placeholder.split('.')[0] if '.' in placeholder else placeholder
                console.print_info(f"  → versioned: {module_name} = {value}", indent=1)
        
        logger.debug(f'Generated {output_filename} from {os.path.basename(versioned_file)}')

    @staticmethod
    def interpolate_sources(content, config):
        """
        Interpolate {{key.path}} patterns in module source lines only.
        
        Why custom interpolation instead of HIML?
        - HIML only processes YAML files
        - These are Terraform .tf files (HCL syntax)
        - We only interpolate 'source' lines for safety (avoid breaking Terraform syntax)
        
        This method processes terraform configuration line by line, looking for
        module source declarations containing placeholders. Only lines with both
        'source' and '{{...}}' are processed to ensure we don't accidentally
        interpolate other parts of the configuration.
        
        Args:
            content: The terraform file content as string
            config: Configuration dictionary for value lookup
            
        Returns:
            Tuple of (interpolated_content, interpolations)
            - interpolated_content: String with interpolated values
            - interpolations: List of (placeholder, value) tuples for display
            
        Example:
            Input:
              source = "git::...?ref={{vpc.module_version}}"
            
            Config: {"vpc": {"module_version": "v2.0.0"}}
            
            Output:
              source = "git::...?ref=v2.0.0"
        """
        lines = content.split('\n')
        output_lines = []
        interpolations = []

        for line in lines:
            # Only interpolate lines containing 'source' and placeholders
            if 'source' in line and '{{' in line:
                # Find all {{key.path}} patterns
                placeholders = re.findall(r'\{\{([^}]+)\}\}', line)

                for placeholder in placeholders:
                    # Get value from config using GenericRunner's static helper
                    value = GenericRunner.get_nested_value(config, placeholder)

                    if value is None:
                        raise ValueError(
                            f'Config key "{placeholder}" not found for interpolation.\n'
                            f'Line: {line.strip()}\n'
                            f'Required config keys must be present when using versioned sources.\n'
                            f'Add "{placeholder}" to your hierarchical configuration.'
                        )

                    # Replace placeholder with value
                    line = line.replace(f'{{{{{placeholder}}}}}', str(value))
                    interpolations.append((placeholder, str(value)))
                    logger.debug(f'Interpolated {{{{{placeholder}}}}} -> {value}')

            output_lines.append(line)

        return '\n'.join(output_lines), interpolations


class GenericTerraformRunner(GenericRunner):
    """
    Base class for Terraform and TFE runners.
    
    Provides shared functionality:
    - Versioned module source processing
    - Composition file handling
    - Path management utilities
    """

    def __init__(self, kompos_config, config_path, execute, runner_type):
        super(GenericTerraformRunner, self).__init__(kompos_config, config_path, execute, runner_type)

        # Get versioned extension from config (default: .tf.versioned)
        self.versioned_extension = self.kompos_config.get_runtime_setting(
            self.runner_type, 'versioned_extension', '.tf.versioned')

        # Load system exclusion keys from config (required in .komposconfig.yaml)
        system_keys_config = self.kompos_config.kompos.get('compositions', {}).get('system_keys', {})

        # Always exclude 'komposconfig' key from output (Kompos runtime settings)
        self.TERRAFORM_SYSTEM_KEYS = ['komposconfig'] + system_keys_config.get('terraform', [])
        self.TFE_SYSTEM_KEYS = ['komposconfig'] + system_keys_config.get('tfe', [])

        # Load hierarchical config values from .komposconfig.yaml
        self.base_dir = self.kompos_config.get_runtime_setting(self.runner_type, 'base_dir', './generated')
        self.use_composition_subdir = self.kompos_config.get_runtime_setting(self.runner_type, 'use_composition_subdir',
                                                                             True)

    def get_source_composition_path(self, composition, raw_config):
        """
        Get path to source composition templates.
        
        Args:
            composition: Composition name (e.g., 'cluster')
            raw_config: Configuration dictionary with cloud type
            
        Returns:
            Path to source composition directory
        """
        return os.path.join(
            self.kompos_config.local_path(self.runner_type),
            self.kompos_config.root_path(self.runner_type),
            raw_config["cloud"]["provider"],
            composition
        )

    def process_composition_files(self, source_dir, target_dir, raw_config):
        """
        Process all composition files (versioned + static).
        
        Handles:
        - .tf.versioned files → process and generate .tf
        - Static .tf files → copy as-is (unless they have .versioned counterpart)
        - Other files → copy as-is
        
        Args:
            source_dir: Source composition directory
            target_dir: Target directory for generated files
            raw_config: Configuration for interpolation
            
        Returns:
            tuple: (processed_count, copied_count)
        """
        if not os.path.exists(source_dir):
            logger.warning(f'Source composition directory does not exist: {source_dir}')
            return 0, 0

        return TerraformVersionedSourceProcessor.process(
            source_dir, target_dir, raw_config, self.versioned_extension)

    def is_versioned_module_sources_enabled(self):
        """Check if versioned module sources feature is enabled."""
        return self.kompos_config.terraform_versioned_module_sources_enabled()

    def build_output_path(self, base_dir, name=None, filename=None, use_subdir=True):
        """
        Build output path with optional subdirectory structure.
        
        Provides consistent path construction across runners with configurable
        subdirectory nesting.
        
        Args:
            base_dir: Base output directory
            name: Optional name for subdirectory (e.g., cluster name)
            filename: Optional filename to append
            use_subdir: Whether to create name subdirectory
            
        Returns:
            Full output path
            
        Examples:
            # Directory only with subdir
            >>> self.build_output_path('/out', name='cluster1')
            '/out/cluster1'
            
            # Directory + filename
            >>> self.build_output_path('/out', 'cluster1', 'vars.yaml')
            '/out/cluster1/vars.yaml'
            
            # Flat structure (no subdir)
            >>> self.build_output_path('/out', 'cluster1', 'vars.yaml', use_subdir=False)
            '/out/vars.yaml'
        """
        output_path = base_dir

        if name and use_subdir:
            output_path = os.path.join(output_path, name)

        if filename:
            output_path = os.path.join(output_path, filename)

        return output_path

    def get_runtime_dir(self, base_dir, cloud_provider, composition, use_cloud_subdir=True):
        """
        Get runtime directory path following standard structure.
        
        Builds consistent runtime paths for Terraform execution across different
        cloud providers and compositions.
        
        Args:
            base_dir: Base output directory
            cloud_provider: Cloud provider name (e.g., 'aws', 'gcp', 'azure')
            composition: Composition name (e.g., 'cluster', 'vpc', 'node-groups')
            use_cloud_subdir: Whether to include cloud provider in path structure
            
        Returns:
            Runtime directory path
            
        Examples:
            >>> self.get_runtime_dir('/tmp/runtime', 'aws', 'cluster')
            '/tmp/runtime/aws/cluster'
            
            >>> self.get_runtime_dir('/tmp/runtime', 'aws', 'vpc', use_cloud_subdir=False)
            '/tmp/runtime/vpc'
        """
        if use_cloud_subdir:
            return os.path.join(base_dir, cloud_provider, composition)
        else:
            return os.path.join(base_dir, composition)

    def ensure_directory(self, path, is_file_path=False, clean=False):
        """
        Ensure a directory exists, with optional cleaning.
        
        Args:
            path: Directory path or file path
            is_file_path: If True, extracts directory from file path
            clean: If True, removes existing directory first (for fresh state)
            
        Returns:
            The directory path that was ensured
            
        Examples:
            # Ensure directory exists
            >>> self.ensure_directory('/tmp/output')
            
            # Extract directory from file path
            >>> self.ensure_directory('/tmp/output/file.txt', is_file_path=True)
            
            # Clean before creating (fresh state)
            >>> self.ensure_directory('/tmp/runtime', clean=True)
        """
        dir_path = os.path.dirname(path) if is_file_path else path

        if clean and os.path.exists(dir_path):
            logger.debug(f'Cleaning directory: {dir_path}')
            shutil.rmtree(dir_path)

        os.makedirs(dir_path, exist_ok=True)
        logger.debug(f'Ensured directory exists: {dir_path}')
        return dir_path

    def generate_terraform_config(self, target_file, config_path, filtered_keys=None, excluded_keys=None,
                                  output_format="json", enclosing_key=None, print_data=False):
        """
        Generate Terraform configuration file from hiera.
        
        Generic method for generating any Terraform config file (provider, tfvars, etc.)
        
        Args:
            target_file: Path to output file
            config_path: Config path for hiera
            filtered_keys: Keys to include (None = all)
            excluded_keys: Keys to exclude (None = none)
            output_format: Output format (json or yaml)
            enclosing_key: Optional enclosing key (e.g., 'config')
            print_data: Whether to print generated data
            
        Returns:
            Path to generated file
        """
        filtered_keys = filtered_keys or []
        excluded_keys = excluded_keys or []

        # Don't log the command here - let the caller provide context

        self.generate_config(
            config_path=config_path,
            exclude_keys=excluded_keys,
            filters=filtered_keys,
            enclosing_key=enclosing_key,
            output_format=output_format,
            output_file=target_file,
            print_data=print_data,
            skip_interpolation_resolving=self.himl_args.skip_interpolation_resolving,
            skip_interpolation_validation=self.himl_args.skip_interpolation_validation,
            skip_secrets=self.himl_args.skip_secrets,
            multi_line_string=True
        )

        return target_file
