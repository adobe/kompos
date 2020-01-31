# Copyright 2019 Adobe. All rights reserved.
# This file is licensed to you under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License. You may obtain a copy
# of the License at http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software distributed under
# the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR REPRESENTATIONS
# OF ANY KIND, either express or implied. See the License for the specific language
# governing permissions and limitations under the License.

import logging
import os

from himl.main import ConfigRunner
from kompos.cli.parser import SubParserConfig
from kompos.hierarchical.composition_config_generator import discover_all_compositions, HierarchicalConfigGenerator, CompositionSorter

logger = logging.getLogger(__name__)


class ConfigGeneratorParserConfig(SubParserConfig):
    def get_name(self):
        return 'config'

    def get_help(self):
        return 'Generate configurations based on a hierarchical structure, with templating support'

    def configure(self, parser):
        return ConfigRunner().get_parser(parser)

    def get_epilog(self):
        return '''
        Examples:
        # Generate config
        kompos data/account=ee-dev/env=dev/region=va6/project=ee/cluster=experiments/composition=helmfiles config --format json --print-data
        '''


class ConfigGeneratorRunner(HierarchicalConfigGenerator):
    def __init__(self, kompos_config, cluster_config_path):
        super(ConfigGeneratorRunner, self).__init__()
        self.kompos_config = kompos_config
        self.cluster_config_path = cluster_config_path

    def run(self, args, extra_args):
        if not os.path.isdir(self.cluster_config_path):
            raise Exception("Provide a valid composition directory path.")

        config_path = os.path.join(self.cluster_config_path, "")

        composition_order = discover_all_compositions(config_path)
        compositions = CompositionSorter(composition_order).get_sorted_compositions(
            config_path
        )
        if not 0 < len(compositions) < 2:
            raise Exception("Provide the path to a single valid composition directory")
        composition = compositions[0]

        filtered_output_keys = self.kompos_config.filtered_output_keys(composition)
        excluded_config_keys = self.kompos_config.excluded_config_keys(composition)

        self.generate_config(
            config_path=self.cluster_config_path,
            filters=filtered_output_keys,
            exclude_keys=excluded_config_keys,
            enclosing_key=args.enclosing_key,
            remove_enclosing_key=args.remove_enclosing_key,
            output_format=args.output_format,
            output_file=args.output_file,
            print_data=True,
            skip_interpolation_resolving=args.skip_interpolation_resolving,
            skip_interpolation_validation=args.skip_interpolation_validation,
            skip_secrets=args.skip_secrets
        )
