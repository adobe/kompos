# Copyright 2019 Adobe. All rights reserved.
# This file is licensed to you under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License. You may obtain a copy
# of the License at http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software distributed under
# the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR REPRESENTATIONS
# OF ANY KIND, either express or implied. See the License for the specific language
# governing permissions and limitations under the License.

import argparse
import logging
import os
from subprocess import Popen, PIPE

from himl import ConfigRunner

from kompos.helpers.himl_helper import HierarchicalConfigGenerator
from kompos.helpers.nix import writeable_nix_out_path, is_nix_enabled, nix_install
from kompos.komposconfig import get_value_or

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

        compositions, paths = discover_compositions(self.config_path)
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

            if self.himl_args.exclude:
                filtered_keys = self.kompos_config.filtered_output_keys(composition) + self.himl_args.filter
                excluded_keys = self.kompos_config.excluded_config_keys(composition) + self.himl_args.exclude

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


def discover_compositions(config_path):
    path_params = dict(split_path(x) for x in config_path.split('/'))

    composition_type = path_params.get(COMPOSITION_KEY, None)
    if not composition_type:
        raise Exception("No composition detected in path.")

    # Check if single composition selected
    composition = path_params.get(composition_type, None)
    if composition:
        return [composition], {composition: config_path}

    # Discover composition paths
    paths = dict()
    compositions = []
    for subpath in os.listdir(config_path):
        if composition_type + "=" in subpath:
            composition = split_path(subpath)[1]
            paths[composition] = os.path.join(config_path, "{}={}".format(composition_type, composition))
            compositions.append(composition)

    return compositions, paths


def sorted_compositions(compositions, composition_order, reverse=False):
    result = list(filter(lambda x: x in compositions, composition_order))
    return tuple(reversed(result)) if reverse else result


def split_path(value, separator='='):
    if separator in value:
        return value.split(separator)
    return [value, ""]


def get_default_output_path(args, raw_config, kompos_config, runner):
    # Use the default local repo (not versioned).
    path = os.path.join(
        kompos_config.local_path(runner),
        kompos_config.root_path(runner),
    )

    # Overwrite with the nix output, if the nix integration is enabled.
    if is_nix_enabled(args, kompos_config.nix()):
        pname = kompos_config.repo_name()

        nix_install(
            pname,
            kompos_config.repo_url(runner),
            get_value_or(raw_config, 'infrastructure/{}/version', 'master'.format(runner)),
            get_value_or(raw_config, 'infrastructure/{}/sha256'.format(runner)),
        )

        # Nix store is read-only, and terraform doesn't work properly outside
        # of the module directory, so as a workaround we're using a temporary directory
        # with the contents of the derivation so terraform can create new files.
        # See: https://github.com/hashicorp/terraform/issues/18030
        # FIXME: Nix store is read-only, and helmfile configuration has a hardcoded path for
        # the generated config, so as a workaround we're using a temporary directory
        # with the contents of the derivation so helmfile can create the config file.

        path = os.path.join(
            writeable_nix_out_path(pname),
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

    if args.himl_args:
        himl_args = parser.parse_args(args.himl_args.split())
        logger.info("Extra himl arguments: %s", himl_args)
        return himl_args
    else:
        return parser.parse_args([])
