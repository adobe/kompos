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

from kompos.hierarchical.composition_helper import get_config_path, get_composition_path
from kompos.hierarchical.config_generator import HierarchicalConfigGenerator
from kompos.komposconfig import TERRAFORM_CONFIG_FILENAME, TERRAFORM_PROVIDER_FILENAME

logger = logging.getLogger(__name__)


class TerraformConfigGenerator(HierarchicalConfigGenerator):

    def __init__(self, excluded_config_keys, filtered_output_keys):
        super(TerraformConfigGenerator, self).__init__()
        self.excluded_config_keys = excluded_config_keys
        self.filtered_output_keys = filtered_output_keys

    def generate_configs(self, himl_args, config_path, config_destination, composition):
        config_path = get_config_path(config_path, composition)
        config_destination = get_composition_path(config_destination, composition)

        self.provider_config(himl_args, config_path, config_destination)
        self.variables_config(himl_args, config_path, config_destination)

    def provider_config(self, himl_args, config_path, composition_path):
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

    def variables_config(self, himl_args, config_path, composition_path):
        output_file = os.path.join(composition_path, TERRAFORM_CONFIG_FILENAME)
        logger.info('Generating terraform config %s', output_file)

        excluded = self.excluded_config_keys.copy() + ["helm", "provider"]
        filtered = self.filtered_output_keys.copy()

        self.generate_config(
            config_path=config_path,
            exclude_keys=excluded,
            filters=filtered,
            enclosing_key="config",
            output_format="json",
            output_file=os.path.expanduser(output_file),
            print_data=True,
            skip_interpolation_resolving=himl_args.skip_interpolation_resolving,
            skip_interpolation_validation=himl_args.skip_interpolation_validation,
            skip_secrets=himl_args.skip_secrets
        )
