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

from himl import ConfigRunner

from kompos.helpers.himl_helper import HierarchicalConfigGenerator
from kompos.helpers.nix import is_nix_enabled, nix_install, writeable_nix_out_path
from kompos.komposconfig import get_value_or

logger = logging.getLogger(__name__)

COMPOSITION_KEY = "composition"


def get_output_path(args, raw_config, kompos_config, runner):
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


def get_compositions(config_path, strict_comp_type, composition_order, reverse=False):
    logging.basicConfig(level=logging.INFO)

    compositions, paths = discover_compositions(config_path)
    if composition_order:
        compositions = sorted_compositions(compositions, composition_order, reverse)

    if not compositions:
        raise Exception(
            "No {} compositions were detected in {}.".format(strict_comp_type, config_path))

    return compositions, paths


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


# Get hiera config path - source config leaf
def get_config_path(path_prefix, composition):
    prefix = os.path.join(path_prefix, '')
    if COMPOSITION_KEY + "=" in path_prefix:
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
