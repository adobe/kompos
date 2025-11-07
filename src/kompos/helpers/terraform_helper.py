# Copyright 2025 Adobe. All rights reserved.
# This file is licensed to you under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License. You may obtain a copy
# of the License at http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software distributed under
# the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR REPRESENTATIONS
# OF ANY KIND, either express or implied. See the License for the specific language
# governing permissions and limitations under the License.

"""Helper for processing Terraform versioned sources."""

import glob
import logging
import os
import re

from kompos.komposconfig import get_value_or

logger = logging.getLogger(__name__)


class TerraformVersionedSourceProcessor:
    """
    Processes .tf.versioned files with module source version interpolation.
    
    This processor enables per-environment/cluster module version pinning by:
    1. Finding .tf.versioned files in composition directories
    2. Interpolating {{key.path}} placeholders with config values
    3. Generating static .tf files for Terraform to use
    
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
    
    def __init__(self, versioned_extension=".tf.versioned"):
        """
        Initialize the processor.
        
        Args:
            versioned_extension: File extension for versioned terraform files
        """
        self.versioned_extension = versioned_extension
    
    def process(self, source_dir, target_dir, config):
        """
        Process all .tf.versioned files in the source directory and generate .tf files in target directory.
        
        Args:
            source_dir: Path to the source composition directory (where .tf.versioned files are)
            target_dir: Path to the runtime directory (where .tf files will be generated)
            config: Configuration dictionary for value interpolation
        """
        # Find all .tf.versioned files in the source directory
        versioned_pattern = os.path.join(source_dir, f"*{self.versioned_extension}")
        versioned_files = glob.glob(versioned_pattern)
        
        if not versioned_files:
            logger.debug('No .tf.versioned files found in %s', source_dir)
            return
        
        logger.info('Processing %d versioned source file(s) from %s', len(versioned_files), source_dir)
        
        for versioned_file in versioned_files:
            self._process_file(versioned_file, target_dir, config)
    
    def _process_file(self, versioned_file, target_dir, config):
        """
        Process a single .tf.versioned file.
        
        Args:
            versioned_file: Path to the .tf.versioned template file
            target_dir: Directory where the generated .tf file will be written
            config: Configuration dictionary for value interpolation
        """
        # Read the versioned file
        with open(versioned_file, 'r') as f:
            content = f.read()
        
        # Interpolate {{key.path}} placeholders
        interpolated_content = self.interpolate_sources(content, config)
        
        # Write to .tf file (remove .versioned extension) in target directory
        output_filename = os.path.basename(versioned_file).replace(self.versioned_extension, '.tf')
        output_file = os.path.join(target_dir, output_filename)
        
        with open(output_file, 'w') as f:
            f.write(interpolated_content)
        
        logger.info('Generated %s from %s', output_filename, os.path.basename(versioned_file))
    
    def interpolate_sources(self, content, config):
        """
        Interpolate {{key.path}} patterns in module source lines only.
        
        This method processes terraform configuration line by line, looking for
        module source declarations containing placeholders. Only lines with both
        'source' and '{{...}}' are processed to ensure we don't accidentally
        interpolate other parts of the configuration.
        
        Args:
            content: The terraform file content as string
            config: Configuration dictionary for value lookup
            
        Returns:
            String with interpolated values
            
        Example:
            Input:
              source = "git::...?ref={{vpc.module_version}}"
            
            Config: {"vpc": {"module_version": "v2.0.0"}}
            
            Output:
              source = "git::...?ref=v2.0.0"
        """
        lines = content.split('\n')
        output_lines = []
        
        for line in lines:
            # Only interpolate lines containing 'source' and placeholders
            if 'source' in line and '{{' in line:
                # Find all {{key.path}} patterns
                placeholders = re.findall(r'\{\{([^}]+)\}\}', line)
                
                for placeholder in placeholders:
                    # Get value from config using dot notation
                    # Convert dots to slashes for get_value_or (vpc.version -> vpc/version)
                    value = get_value_or(config, placeholder.replace('.', '/'))
                    
                    if value is None:
                        raise ValueError(
                            f'Config key "{placeholder}" not found for interpolation.\n'
                            f'Line: {line.strip()}\n'
                            f'Required config keys must be present when using versioned sources.\n'
                            f'Add "{placeholder}" to your hierarchical configuration.'
                        )
                    
                    # Replace placeholder with value
                    line = line.replace(f'{{{{{placeholder}}}}}', str(value))
                    logger.debug('Interpolated {{%s}} -> %s', placeholder, value)
            
            output_lines.append(line)
        
        return '\n'.join(output_lines)


