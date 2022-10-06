# Copyright 2019 Adobe. All rights reserved.
# This file is licensed to you under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License. You may obtain a copy
# of the License at http://www.apache.org/licenses/LICENSE-2.0
import argparse
# Unless required by applicable law or agreed to in writing, software distributed under
# the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR REPRESENTATIONS
# OF ANY KIND, either express or implied. See the License for the specific language
# governing permissions and limitations under the License.

import logging
import os

from himl import ConfigRunner

from kompos.hierarchical.himl_helper import HierarchicalConfigGenerator

logger = logging.getLogger(__name__)

composition_key = "composition"


def get_himl_args(args):
    parser = ConfigRunner.get_parser(argparse.ArgumentParser())

    if args.himl_args:
        himl_args = parser.parse_args(args.himl_args.split())
        logger.info("Extra himl arguments: %s", himl_args)
        return himl_args
    else:
        return parser.parse_args([])


def get_raw_config(config_path, composition, excluded_config_keys, filtered_output_keys):
    generator = HierarchicalConfigGenerator()
    return generator.generate_config(
        config_path=get_config_path(config_path, composition),
        exclude_keys=excluded_config_keys,
        filters=filtered_output_keys,
        skip_interpolation_validation=True,
        skip_secrets=True
    )


def get_compositions(path, composition_order, comp_type, reverse=False):
    logging.basicConfig(level=logging.INFO)

    detected_type, compositions = discover_compositions(path)
    compositions = sorted_compositions(compositions, composition_order, reverse)

    if not compositions:
        raise Exception(
            "No {} compositions were detected in {}.".format(comp_type, path))
    if detected_type != comp_type:
        raise Exception("Failed to detect composition type.")

    return detected_type, compositions


def discover_compositions(path):
    path_params = dict(split_path(x) for x in path.split('/'))
    composition_type = path_params.get(composition_key, None)

    if not composition_type:
        raise Exception("No composition detected in path.")

    # check if single composition selected
    composition = path_params.get(composition_type, None)
    if composition:
        return composition_type, [composition]

    # discover compositions
    compositions = []
    subpaths = os.listdir(path)
    for subpath in subpaths:
        if composition_type + "=" in subpath:
            composition = split_path(subpath)[1]
            compositions.append(composition)

    return composition_type, compositions


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
    if composition_key + "=" in path_prefix:
        return path_prefix
    else:
        return "{}composition={}".format(prefix, composition)


# Get target composition path - generated config
def get_composition_path(path_prefix, composition):
    prefix = os.path.join(path_prefix, '')
    if composition in path_prefix:
        return path_prefix
    else:
        return "{}{}/".format(prefix, composition)
