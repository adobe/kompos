# Copyright 2019 Adobe. All rights reserved.
# This file is licensed to you under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License. You may obtain a copy
# of the License at http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software distributed under
# the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR REPRESENTATIONS
# OF ANY KIND, either express or implied. See the License for the specific language
# governing permissions and limitations under the License.

import logging

from himl import ConfigRunner

from kompos.parser import SubParserConfig
from kompos.runners.runner import GenericRunner

logger = logging.getLogger(__name__)

RUNNER_TYPE = "config"


class ConfigRenderParserConfig(SubParserConfig):
    def get_name(self):
        return RUNNER_TYPE

    def get_help(self):
        return 'Generate configurations based on a hierarchical structure, with templating support'

    def configure(self, parser):
        ConfigRunner().get_parser(parser)

    def get_epilog(self):
        return '''
        Examples:
        # Generate config
        kompos data/account=ee-dev/env=dev/region=va6/project=ee/cluster=experiments/composition=helmfiles config --format json --print-data
        '''


class ConfigRenderRunner(GenericRunner):
    def __init__(self, kompos_config, full_config_path, config_path, execute):
        super(ConfigRenderRunner, self).__init__(kompos_config, full_config_path, config_path, execute, RUNNER_TYPE)

    def run(self, args, extra_args):
        composition_order = None
        compositions, paths = get_compositions(self.config_path, RUNNER_TYPE, composition_order, reverse)

        return self.run_compositions(args, extra_args, compositions, paths)

    def run_compositions(self, args, extra_args, compositions, paths):
        for composition in compositions:
            logger.info("Running composition: %s", composition)

            composition_path = paths[composition]
            filtered_keys = self.kompos_config.filtered_output_keys(composition)
            excluded_keys = self.kompos_config.excluded_config_keys(composition)

            if self.himl_args.exclude:
                filtered_keys = self.kompos_config.filtered_output_keys(composition) + self.himl_args.filter
                excluded_keys = self.kompos_config.excluded_config_keys(composition) + self.himl_args.exclude

            self.generate_config(
                config_path=composition_path,
                filters=filtered_keys,
                exclude_keys=excluded_keys,
                enclosing_key=args.enclosing_key,
                remove_enclosing_key=args.remove_enclosing_key,
                output_format=args.output_format,
                output_file=args.output_file,
                print_data=True,
                skip_interpolation_resolving=args.skip_interpolation_resolving,
                skip_interpolation_validation=args.skip_interpolation_validation,
                skip_secrets=args.skip_secrets,
                multi_line_string=True
            )
