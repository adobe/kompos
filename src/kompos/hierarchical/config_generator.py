# Copyright 2019 Adobe. All rights reserved.
# This file is licensed to you under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License. You may obtain a copy
# of the License at http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software distributed under
# the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR REPRESENTATIONS
# OF ANY KIND, either express or implied. See the License for the specific language
# governing permissions and limitations under the License.


from himl.config_generator import ConfigProcessor

from kompos import display


class HierarchicalConfigGenerator:
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
            skip_secrets=False,
            multi_line_string=False
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
            skip_secrets,
            multi_line_string
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
            skip_secrets=skip_secrets,
            multi_line_string=multi_line_string
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
            multi_line_string=False
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
        if multi_line_string:
            command += " --multi-line-string"

        return command


