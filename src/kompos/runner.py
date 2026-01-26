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
from typing import Any

from himl import ConfigRunner

from kompos.helpers.himl_helper import HierarchicalConfigGenerator

logger = logging.getLogger(__name__)

COMPOSITION_KEY = "composition"


class GenericRunner(HierarchicalConfigGenerator):
    def __init__(self, kompos_config, full_config_path, config_path, execute, runner_type):
        super(GenericRunner, self).__init__()

        logging.basicConfig(level=logging.INFO)

        self.execute = execute

        self.runner_type = runner_type
        self.validate_runner = True

        self.kompos_config = kompos_config
        self.full_config_path = full_config_path
        self.config_path = config_path
        self.himl_args = None
        self.reverse = False
        self.ordered_compositions = False
        self.generate_output = True

    def run(self, args, extra_args):
        logger.info("Runner: %s", self.runner_type)

        if len(extra_args) > 1:
            logger.info("Found extra_args %s", extra_args)

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
                "No {} compositions were detected in {}.".format(self.runner_type, self.config_path))

        return compositions, paths

    def get_raw_config(self, config_path, composition):
        self.kompos_config.excluded_config_keys(composition),
        self.kompos_config.filtered_output_keys(composition)

        return self.generate_config(
            config_path=config_path,
            exclude_keys=self.kompos_config.excluded_config_keys(composition),
            filters=self.kompos_config.filtered_output_keys(composition),
            skip_interpolation_validation=True,
            skip_secrets=True
        )

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
                logger.debug('Acquired kompos lock: %s', lock_file)
            except IOError:
                logger.error('Another kompos process is already running. Please wait or kill the other process.')
                logger.error('Lock file: %s', lock_file)
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
                    logger.warning('Failed to release lock: %s', e)

    def _run_compositions_internal(self, args, extra_args, compositions, paths):
        for composition in compositions:
            logger.info("Running composition: %s", composition)

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
                    "Command finished with nonzero exit code for composition '%s'."
                    "Will skip remaining compositions.", composition
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


def discover_compositions(config_path, kompos_config=None, runner_type=None):
    path_params = dict(split_path(x) for x in config_path.split('/'))

    composition_type = path_params.get(COMPOSITION_KEY, None)
    if not composition_type:
        # No composition in path - return a dummy composition for config rendering
        logger.warning("No composition detected in path. Config will be rendered at this level.")
        return ['config'], {'config': config_path}

    # Check if single composition selected
    composition = path_params.get(composition_type, None)
    if composition:
        return [composition], {composition: config_path}

    # Default: Discover composition paths from filesystem
    paths = {}
    compositions = []
    for subpath in os.listdir(config_path):
        if composition_type + "=" in subpath:
            composition = split_path(subpath)[1]
            paths[composition] = os.path.join(config_path, "{}={}".format(composition_type, composition))
            compositions.append(composition)

    # If nothing found on filesystem, fallback to config
    if not compositions and kompos_config and runner_type:
        config_compositions = kompos_config.composition_order(runner_type, default=None)
        if config_compositions:
            logger.info("No compositions found on filesystem. Using .komposconfig.yaml: %s", config_compositions)
            for comp in config_compositions:
                comp_path = os.path.join(config_path, "{}={}".format(composition_type, comp))
                paths[comp] = comp_path
                if not os.path.exists(comp_path):
                    logger.warning("Composition %s defined in config but path not found: %s", comp, comp_path)
            return config_compositions, paths

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
        logging.exception("Runner {} does not appear to be installed, "
                          "please ensure terraform is in your PATH".format(runner))
        exit(1)

    expected_version = kompos_config.runner_version(runner)
    current_version, execution_error = execution.communicate()
    current_version = current_version.decode('utf-8').split('\n', 1)[0]

    if expected_version not in current_version:
        raise Exception("Runner [{}] should be {}, but you have {}. Please change your version.".format(
            runner, expected_version, current_version))

    return


def get_himl_args(args):
    parser = ConfigRunner.get_parser(argparse.ArgumentParser())

    # For config command, HIML args are already parsed directly into args
    # ConfigRunner().get_parser() adds all HIML args to the config subcommand
    if hasattr(args, 'command') and args.command == 'config':
        logger.info("Using HIML arguments from config command")
        return args
    
    # For tfe command, HIML args are mixed with TFE-specific args
    # Return full args object to include both TFE and HIML args
    if hasattr(args, 'command') and args.command == 'tfe':
        logger.info("Using HIML arguments from tfe command")
        return args

    # For terraform/helmfile commands, use --himl flag if provided
    if hasattr(args, 'himl_args') and args.himl_args:
        himl_args = parser.parse_args(args.himl_args.split())
        logger.info("Extra himl arguments for %s: %s", args.command, himl_args)
        return himl_args

    # Default: return empty parsed args with defaults
    return parser.parse_args([])
