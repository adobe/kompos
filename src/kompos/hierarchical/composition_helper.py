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

from kompos.hierarchical.config_generator import HierarchicalConfigGenerator

logger = logging.getLogger(__name__)


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


def discover_compositions(path, composition_type="composition"):
    # check single composition selected
    path_params = dict(split_path(x) for x in path.split('/'))
    composition = path_params.get(composition_type, None)
    if composition:
        return [composition]

    # discover compositions
    compositions = []
    subpaths = os.listdir(path)
    for subpath in subpaths:
        if composition_type + "=" in subpath:
            composition = split_path(subpath)[1]
            compositions.append(composition)

    return compositions


def sorted_compositions(compositions, composition_order, reverse=False):
    result = list(filter(lambda x: x in compositions, composition_order))
    return tuple(reversed(result)) if reverse else result


def split_path(value, separator='='):
    if separator in value:
        return value.split(separator)
    return [value, ""]


# Get hiera config path - source config leaf
def get_config_path(path_prefix, composition):
    prefix = os.path.join(path_prefix, '')
    if "composition=" in path_prefix:
        if "composition=custom" not in path_prefix:
            return path_prefix
        if "composition=custom" and "type=" in path_prefix:
            return path_prefix
        else:
            return "{}type={}".format(prefix, composition)
    else:
        return "{}composition={}".format(prefix, composition)


# Get target composition path - generated config
def get_composition_path(path_prefix, composition, raw_config):
    prefix = os.path.join(path_prefix, '')
    if "custom" in path_prefix:
        try:
            custom_composition = raw_config["custom"]["type"]
            logger.info("Appending custom composition: %s", custom_composition)
            return "{}{}/".format(prefix, custom_composition)
        except KeyError:
            logger.info("No custom composition type found")
            raise
    elif composition in path_prefix:
        return path_prefix
    else:
        return "{}{}/".format(prefix, composition)



