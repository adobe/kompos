# Copyright 2019 Adobe. All rights reserved.
# This file is licensed to you under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License. You may obtain a copy
# of the License at http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software distributed under
# the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR REPRESENTATIONS
# OF ANY KIND, either express or implied. See the License for the specific language
# governing permissions and limitations under the License.

from himl.config_generator import ConfigProcessor

from kompos import Executor, display
from kompos.komposconfig import TERRAFORM_CONFIG_FILENAME, TERRAFORM_PROVIDER_FILENAME

import logging
import os

logger = logging.getLogger(__name__)


def discover_all_compositions(path):
    path_params = dict(split_path(x) for x in path.split('/'))

    composition = path_params.get("composition", None)
    if composition:
        return [composition]

    return get_compositions_in_path(path)


def get_compositions_in_path(path):
    compositions = []
    subpaths = os.listdir(path)
    for subpath in subpaths:
        if "composition=" in subpath:
            composition = split_path(subpath)[1]
            compositions.append(composition)
    return compositions


def run_sh(command, cwd=None, exit_on_error=True):
    args = {"command": command}
    execute = Executor()
    exit_code = execute(args, cwd=cwd)
    if exit_code != 0:
        logger.error("Command finished with non zero exit code.")
        if exit_on_error:
            exit(exit_code)


def split_path(value, separator='='):
    if separator in value:
        return value.split(separator)
    return [value, ""]


def get_config_path(path_prefix, composition):
    prefix = os.path.join(path_prefix, '')
    return path_prefix if "composition=" in path_prefix else "{}composition={}".format(
        prefix, composition)


def get_composition_path(path_prefix, composition):
    prefix = os.path.join(path_prefix, '')
    return path_prefix if composition in path_prefix else "{}{}/".format(
        prefix, composition)


class CompositionSorter():
    def __init__(self, composition_order):
        self.composition_order = composition_order

    def get_sorted_compositions(self, path, reverse=False):
        discovered_compositions = discover_all_compositions(path)
        compositions = self.sort_compositions(discovered_compositions, reverse)
        return compositions

    def sort_compositions(self, compositions, reverse=False):
        result = list(
            filter(
                lambda x: x in compositions,
                self.composition_order))
        return tuple(reversed(result)) if reverse else result


class HierarchicalConfigGenerator():
    def __init__(self):
        self.config_processor = ConfigProcessor()

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
        skip_secrets=False
    ):
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
            skip_secrets
        )

        display(cmd, color="yellow")

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
            skip_secrets=skip_secrets
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
        skip_secrets=False
    ):
        command = "kompos {} config --format {}".format(
            config_path, output_format)
        for filter in filters:
            command += " --filter {}".format(filter)
        for exclude in exclude_keys:
            command += " --exclude {}".format(exclude)
        if enclosing_key:
            command += " --enclosing-key {}".format(enclosing_key)
        if remove_enclosing_key:
            command += " --remove-enclosing-key {}".format(remove_enclosing_key)
        if output_file:
            command += " --output-file {}".format(output_file)
        if print_data:
            command += " --print-data"
        if skip_interpolation_resolving:
            command += " --skip-interpolation-resolving"
        if skip_interpolation_validation:
            command += " --skip-interpolation-validation"
        if skip_secrets:
            command += " --skip-secrets"

        return command


class PreConfigGenerator(HierarchicalConfigGenerator):

    def __init__(self, excluded_config_keys, filtered_output_keys):
        super(PreConfigGenerator, self).__init__()
        self.excluded_config_keys = excluded_config_keys
        self.filtered_output_keys = filtered_output_keys

    def pre_generate_config(self, config_path, composition, skip_secrets=True):
        return self.generate_config(
            config_path=get_config_path(config_path, composition),
            exclude_keys=self.excluded_config_keys,
            filters=self.filtered_output_keys,
            skip_interpolation_validation=True,
            skip_secrets=skip_secrets
        )


class TerraformConfigGenerator(HierarchicalConfigGenerator):

    def __init__(self, excluded_config_keys, filtered_output_keys):
        super(TerraformConfigGenerator, self).__init__()
        self.excluded_config_keys = excluded_config_keys
        self.filtered_output_keys = filtered_output_keys

    def generate_files(self, himl_args, config_path, composition_path, composition):
        config_path = get_config_path(config_path, composition)
        composition_path = get_composition_path(composition_path, composition)

        self.generate_provider_config(himl_args, config_path, composition_path)
        self.generate_variables_config(himl_args, config_path, composition_path)

    def generate_provider_config(self, himl_args, config_path, composition_path):
        output_file = os.path.join(composition_path, TERRAFORM_PROVIDER_FILENAME)
        logger.info('Generating terraform config %s', output_file)

        filters = self.filtered_output_keys.copy() + ["provider", "terraform"]

        excluded = self.excluded_config_keys.copy()
        if himl_args.exclude:
            excluded = self.excluded_config_keys.copy() + himl_args.exclude

        self.generate_config(
            config_path=config_path,
            exclude_keys=excluded,
            filters=filters,
            output_format="json",
            output_file=output_file,
            print_data=False,
            skip_interpolation_resolving=himl_args.skip_interpolation_resolving,
            skip_interpolation_validation=himl_args.skip_interpolation_validation,
            skip_secrets=himl_args.skip_secrets
        )

    def generate_variables_config(self, himl_args, config_path, composition_path):
        output_file = os.path.join(composition_path, TERRAFORM_CONFIG_FILENAME)
        logger.info('Generating terraform config %s', output_file)

        excluded = self.excluded_config_keys.copy() + ["helm", "provider"]

        self.generate_config(
            config_path=config_path,
            exclude_keys=excluded,
            filters=self.filtered_output_keys,
            enclosing_key="config",
            output_format="json",
            output_file=os.path.expanduser(output_file),
            print_data=True,
            skip_interpolation_resolving=himl_args.skip_interpolation_resolving,
            skip_interpolation_validation=himl_args.skip_interpolation_validation,
            skip_secrets=himl_args.skip_secrets
        )
