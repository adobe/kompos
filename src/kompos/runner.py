# Copyright 2019 Adobe. All rights reserved.
# This file is licensed to you under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License. You may obtain a copy
# of the License at http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software distributed under
# the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR REPRESENTATIONS
# OF ANY KIND, either express or implied. See the License for the specific language
# governing permissions and limitations under the License.

import argparse
import fcntl
import logging
import os
from subprocess import Popen, PIPE

from himl import ConfigRunner
from himl.config_generator import ConfigProcessor

logger = logging.getLogger(__name__)

COMPOSITION_KEY = "composition"


class GenericRunner:
    """
    Base class for all Kompos runners.
    
    Provides:
    - HIML config generation via ConfigProcessor
    - Composition discovery and orchestration
    - Common utilities for all runner types (terraform, helmfile, tfe, config, explore)
    """

    def __init__(self, kompos_config, config_path, execute, runner_type):
        # Initialize HIML config processor
        self.config_processor = ConfigProcessor()

        logging.basicConfig(level=logging.INFO)

        self.execute = execute
        self.runner_type = runner_type
        self.validate_runner = True

        self.kompos_config = kompos_config
        self.config_path = config_path
        self.himl_args = None
        self.reverse = False
        self.ordered_compositions = False

        self.generate_output = True

    @staticmethod
    def extract_format_from_extension(extension):
        """
        Extract output format (yaml/json) from file extension.
        
        Args:
            extension: File extension (e.g., '.workspace.yaml', '.tfvars.json')
        
        Returns:
            'yaml' or 'json'
        
        Examples:
            '.workspace.yaml' -> 'yaml'
            '.tfvars.yaml' -> 'yaml'
            '.json' -> 'json'
            '.workspace.json' -> 'json'
        """
        if 'yaml' in extension.lower() or 'yml' in extension.lower():
            return 'yaml'
        elif 'json' in extension.lower():
            return 'json'
        # Default to yaml if uncertain
        return 'yaml'

    def generate_config(
            self,
            config_path,
            filters=(),
            exclude_keys=(),
            enclosing_key=None,
            remove_enclosing_key=None,
            output_format="yaml",
            print_data=False,
            output_file=None,
            skip_interpolation_resolving=False,
            skip_interpolation_validation=False,
            skip_secrets=False,
            multi_line_string=False,
            type_strategies=[(list, ["append"]), (dict, ["merge"])],
            fallback_strategies=["override"],
            type_conflict_strategies=["override"],
            silent=False  # Don't print command (for internal/trace operations)
    ):
        """Generate hierarchical configuration using HIML."""
        cmd = self.get_sh_command(
            config_path,
            filters,
            exclude_keys,
            enclosing_key,
            remove_enclosing_key,
            output_format,
            print_data,
            output_file,
            skip_interpolation_resolving,
            skip_interpolation_validation,
            skip_secrets,
            multi_line_string,
        )

        if not silent:
            logger.debug(cmd)

        return self.config_processor.process(
            path=config_path,
            filters=filters,
            exclude_keys=exclude_keys,
            enclosing_key=enclosing_key,
            remove_enclosing_key=remove_enclosing_key,
            output_format=output_format,
            output_file=output_file,
            print_data=print_data,
            skip_interpolations=skip_interpolation_resolving,
            skip_interpolation_validation=skip_interpolation_validation,
            skip_secrets=skip_secrets,
            multi_line_string=multi_line_string,
            type_strategies=type_strategies,
            fallback_strategies=fallback_strategies,
            type_conflict_strategies=type_conflict_strategies
        )

    @staticmethod
    def get_sh_command(
            config_path,
            filters=(),
            exclude_keys=(),
            enclosing_key=None,
            remove_enclosing_key=None,
            output_format="yaml",
            print_data=False,
            output_file=None,
            skip_interpolation_resolving=False,
            skip_interpolation_validation=False,
            skip_secrets=False,
            multi_line_string=False,
    ):
        """Build shell command string for displaying HIML invocation."""
        command = f"kompos {config_path} config --format {output_format}"
        for filter in filters:
            command += f" --filter {filter}"
        for exclude in exclude_keys:
            command += f" --exclude {exclude}"
        if enclosing_key:
            command += f" --enclosing-key {enclosing_key}"
        if remove_enclosing_key:
            command += f" --remove-enclosing-key {remove_enclosing_key}"
        if output_file:
            command += f" --output-file {output_file}"
        if print_data:
            command += " --print-data"
        if skip_interpolation_resolving:
            command += " --skip-interpolation-resolving"
        if skip_interpolation_validation:
            command += " --skip-interpolation-validation"
        if skip_secrets:
            command += " --skip-secrets"
        if multi_line_string:
            command += " --multi-line-string"

        return command

    def run(self, args, extra_args):
        logger.debug(f"Runner: {self.runner_type}")

        if len(extra_args) > 1:
            logger.debug(f"Found extra_args {extra_args}")

        self.himl_args = get_himl_args(args)
        self.run_configuration(args)

        # Stop processing if an incompatible runner version is detected.
        if not self.runner_type:
            logger.error("Could not detect runner type and version.")
            exit(1)
        if self.validate_runner:
            validate_runner_version(self.kompos_config, self.runner_type)

        compositions, paths = self.get_compositions()

        return self.run_compositions(args, extra_args, compositions, paths)

    def run_configuration(self, args):
        return

    def get_compositions(self):
        logging.basicConfig(level=logging.INFO)

        compositions, paths = discover_compositions(
            self.config_path,
            self.kompos_config,
            self.runner_type
        )
        if self.ordered_compositions:
            composition_order = self.kompos_config.composition_order(self.runner_type)
            compositions = sorted_compositions(compositions, composition_order, self.reverse)

        if not compositions:
            raise Exception(
                f"No {self.runner_type} compositions were detected in {self.config_path}.")

        return compositions, paths

    def get_raw_config(self, config_path, composition):
        """
        Generate raw config WITHOUT exclusions/filters for internal use.
        
        This config is used by Kompos to read metadata like composition.instance.
        All keys must be available for interpolation (exclusions break references).
        
        Exclusions/filters are applied separately when generating final output files.
        """
        return self.generate_config(
            config_path=config_path,
            exclude_keys=[],  # No exclusions - all keys available for interpolation
            filters=[],  # No filters - generate complete config
            skip_interpolation_validation=True,
            skip_secrets=True
        )

    def get_composition_name(self, raw_config):
        """
        Get the resolved composition instance identifier from layered config.
        
        Reads composition.instance which uses pure Himl interpolation:
          composition.instance: "{{account.name}}"  or  "{{cluster.fullName}}"
        
        Args:
            raw_config: Raw configuration dictionary from himl
        
        Returns:
            str: Resolved instance identifier (e.g., "my-account", "my-cluster-us-east-1")
            
        Example:
            name = self.get_composition_name(raw_config)
            if not name:
                return  # Skip processing
        """
        return self.kompos_config.get_composition_name(
            raw_config=raw_config,
            get_nested_value_fn=self.get_nested_value
        )

    def get_composition_output_dir(self, raw_config):
        """
        Get the composition instance directory name from layered config.
        
        Reads composition.output_dir (or falls back to composition.instance) which uses
        pure Himl interpolation:
          composition.instance: "{{account.name}}"  or  "{{cluster.fullName}}"
        
        This is Level 3 in the output hierarchy:
          base/composition_type/composition_instance/
        
        Args:
            raw_config: Raw configuration dictionary from himl
        
        Returns:
            str: Resolved directory name (e.g., "my-account", "my-cluster-us-east-1")
        """
        # Try composition.output_dir first (for cases where name and dir differ)
        output_dir = self.get_nested_value(raw_config, 'composition.output_dir')
        if not output_dir or '{{' in str(output_dir):
            # Fallback to composition.instance (typical case - instance = dir)
            output_dir = self.get_composition_name(raw_config)
        return output_dir

    def run_compositions(self, args, extra_args, compositions, paths):
        # Acquire lock to prevent concurrent kompos runs from interfering
        lock_file = None
        lock_fd = None

        try:
            lock_file = os.path.join(os.getcwd(), '.kompos-runtime', '.lock')
            os.makedirs(os.path.dirname(lock_file), exist_ok=True)
            lock_fd = open(lock_file, 'w')

            # Try to acquire exclusive lock (non-blocking)
            try:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                logger.debug(f'Acquired kompos lock: {lock_file}')
            except IOError:
                logger.error('Another kompos process is already running. Please wait or kill the other process.')
                logger.error(f'Lock file: {lock_file}')
                return 1

            return self._run_compositions_internal(args, extra_args, compositions, paths)

        finally:
            # Release lock and cleanup
            if lock_fd:
                try:
                    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
                    lock_fd.close()
                    logger.debug('Released kompos lock')
                except Exception as e:
                    logger.warning(f'Failed to release lock: {e}')

    def _run_compositions_internal(self, args, extra_args, compositions, paths):
        for composition in compositions:
            logger.debug(f"→ {self.runner_type.upper()}: {composition}")

            # Set current path
            config_path = paths[composition]

            # Raw config generation
            raw_config = self.get_raw_config(config_path, composition)

            # Generate output paths for configs
            default_output_path = None
            if self.generate_output:
                default_output_path = get_default_output_path(args, raw_config, self.kompos_config, self.runner_type)

            # Set default key filters
            filtered_keys = self.kompos_config.filtered_output_keys(composition)
            excluded_keys = self.kompos_config.excluded_config_keys(composition)

            # Add CLI-provided filters and excludes to config-based ones
            if self.himl_args.filter:
                filtered_keys = filtered_keys + self.himl_args.filter
            if self.himl_args.exclude:
                excluded_keys = excluded_keys + self.himl_args.exclude

            # Runner pre-configuration
            self.execution_configuration(composition, config_path, default_output_path, raw_config,
                                         filtered_keys, excluded_keys)

            # Execute runner
            return_code = self.execute(self.execution(args, extra_args, default_output_path, composition, raw_config))
            if return_code != 0:
                logger.error(
                    f"Command finished with nonzero exit code for composition '{composition}'."
                    f"Will skip remaining compositions."
                )
                return return_code

            # Run some code after execution
            self.execution_post_action()

        return 0

    def execution_configuration(self, composition, config_path, default_output_path, raw_config,
                                filtered_keys, excluded_keys):
        return

    @staticmethod
    def execution(args, extra_args, default_output_path, composition, raw_config):
        return

    @staticmethod
    def execution_post_action():
        return

    @staticmethod
    def get_nested_value(data, key_path, default=None):
        """
        Get a nested value from a dict using a dotted key path.
        Supports both dictionary keys and list indices.
        
        Args:
            data: Dictionary to extract value from
            key_path: Dot-separated path to the value (e.g., 'cluster.fullName', 'workspaces.0.name')
            default: Default value to return if not found (default: None)
        
        Returns:
            The value at the key path, or default if not found
        
        Examples:
            >>> data = {'cluster': {'fullName': 'my-cluster', 'name': 'cluster1'}}
            >>> GenericRunner.get_nested_value(data, 'cluster.fullName')
            'my-cluster'
            >>> data = {'workspaces': [{'name': 'ws1'}, {'name': 'ws2'}]}
            >>> GenericRunner.get_nested_value(data, 'workspaces.0.name')
            'ws1'
            >>> GenericRunner.get_nested_value(data, 'cluster.missing')
            None
            >>> GenericRunner.get_nested_value(data, 'cluster.missing', 'default-cluster')
            'default-cluster'
        """
        if not key_path:
            return default

        keys = key_path.split('.')
        value = data

        for key in keys:
            # Try to use as array index if it's a digit
            if isinstance(value, list) and key.isdigit():
                idx = int(key)
                if 0 <= idx < len(value):
                    value = value[idx]
                else:
                    return default
            # Otherwise use as dict key
            elif isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default

        return value

    @staticmethod
    def flatten_dict(d, parent_key='', sep='.'):
        """
        Flatten nested dictionary into dot-notation keys.
        
        Args:
            d: Dictionary to flatten
            parent_key: Parent key for recursion
            sep: Separator for key concatenation (default: '.')
        
        Returns:
            Flattened dictionary with dot-notation keys
        
        Examples:
            >>> data = {'vpc': {'cidr': '10.0.0.0/16'}}
            >>> GenericRunner.flatten_dict(data)
            {'vpc.cidr': '10.0.0.0/16'}
            >>> data = {'cluster': {'name': 'prod', 'region': 'us-east-1'}}
            >>> GenericRunner.flatten_dict(data)
            {'cluster.name': 'prod', 'cluster.region': 'us-east-1'}
        """
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(GenericRunner.flatten_dict(v, new_key, sep=sep).items())
            else:
                items.append((new_key, v))
        return dict(items)


def discover_compositions(config_path, kompos_config=None, runner_type=None):
    path_params = dict(split_path(x) for x in config_path.split('/'))

    # Check if composition is directly specified in path (e.g., composition=cluster)
    composition = path_params.get(COMPOSITION_KEY, None)
    if composition:
        # Single composition specified - return it directly
        return [composition], {composition: config_path}

    # No composition specified - discover from filesystem or config
    # This happens when path ends at cluster level (e.g., cluster=demo-cluster-01)
    logger.info("No composition specified in path. Discovering compositions...")

    # Try to discover composition paths from filesystem
    paths = {}
    compositions = []
    for subpath in os.listdir(config_path):
        if COMPOSITION_KEY + "=" in subpath:
            comp_name = split_path(subpath)[1]
            comp_path = os.path.join(config_path, subpath)
            paths[comp_name] = comp_path
            compositions.append(comp_name)

    # If nothing found on filesystem, fallback to .komposconfig.yaml
    if not compositions and kompos_config and runner_type:
        config_compositions = kompos_config.composition_order(runner_type, default=None)
        if config_compositions:
            logger.info(f"No compositions found on filesystem. Using .komposconfig.yaml: {config_compositions}")
            for comp in config_compositions:
                comp_path = os.path.join(config_path, f"{COMPOSITION_KEY}={comp}")
                paths[comp] = comp_path
                if not os.path.exists(comp_path):
                    logger.warning(f"Composition {comp} defined in config but path not found: {comp_path}")
            return config_compositions, paths

    if not compositions:
        # No composition in path and none discovered - return dummy for config rendering
        logger.warning("No composition detected in path. Config will be rendered at this level.")
        return ['config'], {'config': config_path}

    return compositions, paths


def sorted_compositions(compositions, composition_order, reverse=False):
    result = list(filter(lambda x: x in compositions, composition_order))
    return tuple(reversed(result)) if reverse else result


def split_path(value, separator='='):
    if separator in value:
        return value.split(separator)
    return [value, ""]


def get_default_output_path(args, raw_config, kompos_config, runner):
    # Use a dedicated runtime directory (not versioned)
    # This keeps generated files separate from source files
    runtime_base = os.path.join(
        os.getcwd(),
        '.kompos-runtime'
    )

    path = os.path.join(
        runtime_base,
        runner,
        kompos_config.root_path(runner),
    )

    return path


def validate_runner_version(kompos_config, runner):
    """
    Check if runner binary version is compatible with the
    version specified by the kompos configuration.
    """
    try:
        execution = Popen([runner, '--version'],
                          stdin=PIPE,
                          stdout=PIPE,
                          stderr=PIPE)
    except Exception:
        logging.exception(
            f"Runner {runner} does not appear to be installed, "
            f"please ensure terraform is in your PATH"
        )
        exit(1)

    expected_version = kompos_config.runner_version(runner)
    current_version, execution_error = execution.communicate()
    current_version = current_version.decode('utf-8').split('\n', 1)[0]

    if expected_version not in current_version:
        raise Exception(
            f"Runner [{runner}] should be {expected_version}, but you have {current_version}. "
            f"Please change your version."
        )

    return


def get_himl_args(args):
    parser = ConfigRunner.get_parser(argparse.ArgumentParser())

    # For config command, HIML args are already parsed directly into args
    # ConfigRunner().get_parser() adds all HIML args to the config subcommand
    if hasattr(args, 'command') and args.command == 'config':
        logger.debug("Using HIML arguments from config command")
        return args

    # For tfe command, HIML args are mixed with TFE-specific args
    # Return full args object to include both TFE and HIML args
    if hasattr(args, 'command') and args.command == 'tfe':
        logger.debug("Using HIML arguments from tfe command")
        return args

    # For explore command, return full args for exploration options
    if hasattr(args, 'command') and args.command == 'explore':
        logger.debug("Using arguments from explore command")
        return args

    # For terraform/helmfile commands, use --himl flag if provided
    if hasattr(args, 'himl_args') and args.himl_args:
        himl_args = parser.parse_args(args.himl_args.split())
        logger.info(f"Extra himl arguments for {args.command}: {himl_args}")
        return himl_args

    # Default: return empty parsed args with defaults
    return parser.parse_args([])
