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

from kompos.helpers.composition_helper import get_compositions, get_config_path, \
    get_composition_path, get_raw_config, get_himl_args, get_output_path
from kompos.helpers.himl_helper import HierarchicalConfigGenerator

from kompos.cli.parser import SubParserConfig
from kompos.helpers.runner_helper import validate_runner_version
from kompos.komposconfig import (
    TERRAFORM_CONFIG_FILENAME,
    local_config_dir, TERRAFORM_PROVIDER_FILENAME
)

logger = logging.getLogger(__name__)

# Terraform subcommands that will need re-initialization
SUBCMDS_WITH_INIT = [
    'plan',
    'apply',
    'destroy',
    'import',
    'state'
]

# Terraform subcommands that use the variables file.
SUBCMDS_WITH_VARS = [
    'plan',
    'apply',
    'destroy',
    'import'
]

RUNNER_TYPE = "terraform"


class TerraformParserConfig(SubParserConfig):
    def get_name(self):
        return RUNNER_TYPE

    def get_help(self):
        return 'Wrap common terraform tasks with full templated configuration support'

    def configure(self, parser):
        parser.add_argument('subcommand', help='One of the terraform commands', type=str)
        parser.add_argument('--var',
                            help='the output var to show',
                            type=str,
                            default='')
        parser.add_argument('--module',
                            help='for use with "taint", "untaint" and "import". '
                                 'The module to use. e.g.: vpc', type=str)
        parser.add_argument('--resource',
                            help='for use with "taint", "untaint" and "import".'
                                 'The resource to target. e.g.: aws_instance.nat',
                            type=str)
        parser.add_argument('--name',
                            help='for use with "import". The name or ID of the imported resource. '
                                 'e.g.: i-abcd1234',
                            type=str)
        parser.add_argument('--plan', help='for use with "show", '
                                           'show the plan instead of the statefile',
                            action='store_true')
        parser.add_argument('--state-location', help='control how the remote states are used',
                            choices=['local', 'remote', 'any'], default='any', type=str)
        parser.add_argument('--force-copy',
                            help='for use with "plan" to do force state change '
                                 'automatically during init phase',
                            action='store_true')
        parser.add_argument('--template-location',
                            help='for use with "template". The folder where to save the tf files, '
                                 'without showing',
                            type=str)
        parser.add_argument('--skip-refresh', help='for use with "plan". Skip refresh of statefile',
                            action='store_false', dest='do_refresh')
        parser.set_defaults(do_refresh=True)
        parser.add_argument('--raw-output',
                            help='for use with "plan". Show raw plan output without piping through '
                                 'terraform landscape - https://github.com/coinbase/terraform-landscape '
                                 '(if terraform landscape is not enabled in komposconfig.yaml '
                                 'this will have no impact)', action='store_true',
                            dest='raw_plan_output')
        parser.set_defaults(raw_plan_output=False)
        parser.add_argument('--path-name',
                            help='in case multiple terraform paths are defined, '
                                 'this allows to specify which one to use when running terraform',
                            type=str)
        parser.add_argument('--terraform-path',
                            type=str,
                            default=None,
                            help='Path to terraform files')
        parser.add_argument('--skip-plan',
                            help='for use with "apply"; runs terraform apply without running a plan first',
                            action='store_true')
        parser.add_argument('--auto-approve',
                            help='for use with "apply". Proceeds with the apply without'
                                 'waiting for user confirmation.',
                            action='store_true')
        parser.add_argument('--himl',
                            action='store',
                            dest='himl_args',
                            default=None,
                            help='for passing arguments to himl'
                                 '--himl="--arg1 --arg2" any himl argument is supported wrapped in quotes')
        parser.add_argument('terraform_args',
                            type=str,
                            nargs='*',
                            help='Extra terraform args')

        return parser

    def get_epilog(self):
        return '''
        Examples:
            # Run helmfile sync
            kompos data/env=dev/region=va6/project=ee/cluster=experiments/composition=terraform terraform plan 
            # Run helmfile sync on a single composition
            kompos data/env=dev/region=va6/project=ee/cluster=experiments/composition=terraform/terraform=myterraformcomposition terraform plan
        '''


class TerraformRunner(HierarchicalConfigGenerator):
    def __init__(self, config_path, kompos_config, execute):
        super(TerraformRunner, self).__init__()
        logging.basicConfig(level=logging.INFO)

        self.kompos_config = kompos_config
        self.config_path = config_path
        self.execute = execute

    def run(self, args, extra_args):
        # Stop processing if an incompatible version is detected.
        validate_runner_version(self.kompos_config, RUNNER_TYPE)

        logger.info("Found extra_args %s", extra_args)

        reverse = ("destroy" == args.subcommand)
        detected_type, compositions = get_compositions(self.kompos_config, self.config_path,
                                                       comp_type=RUNNER_TYPE, reverse=reverse)

        return self.run_compositions(args, extra_args, compositions)

    def run_compositions(self, args, extra_args, compositions):
        for composition in compositions:
            logger.info("Running composition: %s", composition)

            # Check if composition has a complete path
            composition_path = self.config_path
            if composition not in composition_path:
                composition_path = self.config_path + "/{}=".format(RUNNER_TYPE) + composition

            raw_config = get_raw_config(composition_path, composition,
                                        self.kompos_config.excluded_config_keys(composition),
                                        self.kompos_config.filtered_output_keys(composition))

            # Generate output paths for configs
            config_destination = os.path.join(get_output_path(args, raw_config, self.kompos_config, RUNNER_TYPE),
                                              raw_config["cloud"]["type"])

            # Generate configs
            self.generate_terraform_configs(get_himl_args(args), composition_path, config_destination, composition)

            # Run terraform
            return_code = self.execute(self.run_terraform(args, extra_args, config_destination, composition))

            if return_code != 0:
                logger.error(
                    "Command finished with nonzero exit code for composition '%s'."
                    "Will skip remaining compositions.", composition
                )
                return return_code

        return 0

    @staticmethod
    def run_terraform(args, extra_args, terraform_path, composition):
        terraform_composition_path = os.path.join(terraform_path, composition)

        var_file = '-var-file="{}"'.format(TERRAFORM_CONFIG_FILENAME) if args.subcommand in SUBCMDS_WITH_VARS else ''
        terraform_env_config = 'export TF_PLUGIN_CACHE_DIR="{}"'.format(local_config_dir())

        cmd = "cd {terraform_path} && " \
              "{remove_local_cache} " \
              "{env_config} ; terraform init && terraform {subcommand} {var_file} {tf_args} {extra_args}".format(
            terraform_path=terraform_composition_path,
            remove_local_cache=remove_local_cache_cmd(args.subcommand),
            subcommand=args.subcommand,
            extra_args=' '.join(extra_args),
            tf_args=' '.join(args.terraform_args),
            var_file=var_file,
            env_config=terraform_env_config)

        return dict(command=cmd)

    def generate_terraform_configs(self, himl_args, config_path, config_destination, composition):
        config_path = get_config_path(config_path, composition)
        config_destination = get_composition_path(config_destination, composition)

        self.provider_config(himl_args, config_path, config_destination, composition)
        self.variables_config(himl_args, config_path, config_destination, composition)

    def provider_config(self, himl_args, config_path, composition_path, composition):
        output_file = os.path.join(composition_path, TERRAFORM_PROVIDER_FILENAME)
        logger.info('Generating terraform config %s', output_file)

        filters = self.kompos_config.filtered_output_keys(composition) + ["provider", "terraform"]
        excluded = self.kompos_config.excluded_config_keys(composition)

        if himl_args.exclude:
            excluded = self.kompos_config.excluded_config_keys(composition) + himl_args.exclude

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

    def variables_config(self, himl_args, config_path, composition_path, composition):
        output_file = os.path.join(composition_path, TERRAFORM_CONFIG_FILENAME)
        logger.info('Generating terraform config %s', output_file)

        excluded = self.kompos_config.excluded_config_keys(composition) + ["provider"]
        filtered = self.kompos_config.filtered_output_keys(composition)

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


def remove_local_cache_cmd(subcommand):
    if subcommand in SUBCMDS_WITH_INIT:
        return 'rm -rf .terraform &&'

    return ''
