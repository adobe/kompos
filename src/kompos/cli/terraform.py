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

from himl.main import ConfigRunner

from kompos.cli.parser import SubParserConfig
from kompos.hierarchical.composition_helper import PreConfigGenerator, get_compositions, get_config_path, \
    get_composition_path
from kompos.hierarchical.config_generator import HierarchicalConfigGenerator
from kompos.hierarchical.terraform_config_generator import TerraformConfigGenerator
from kompos.komposconfig import (
    TERRAFORM_CONFIG_FILENAME,
    get_value_or,
    local_config_dir, TERRAFORM_PROVIDER_FILENAME
)
from kompos.nix import nix_install, writeable_nix_out_path, is_nix_enabled

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


class TerraformParserConfig(SubParserConfig):
    def get_name(self):
        return 'terraform'

    def get_help(self):
        return 'Wrap common terraform tasks with full templated configuration support'

    def configure(self, parser):
        parser.add_argument('subcommand', help='One of the terraform commands', type=str)
        parser.add_argument(
            '--var',
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
        parser.add_argument(
            '--terraform-path',
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
        parser.add_argument(
            'terraform_args',
            type=str,
            nargs='*',
            help='Extra terraform args')

        return parser

    def get_epilog(self):
        return '''
    Examples:
        # Create/update a new cluster with Terraform
        kompos clusters/qe1.yaml terraform plan
        kompos clusters/qe1.yaml terraform apply

        # Run Terraform apply without running a plan first
        kompos clusters/qe1.yaml terraform apply --skip-plan

        # Get rid of a cluster and all of its components
        kompos clusters/qe1.yaml terraform destroy

        # Retrieve all output from a previously created Terraform cluster
        kompos clusters/qe1.yaml terraform output

        # Retrieve a specific output from a previously created Terraform cluster
        kompos clusters/qe1.yaml terraform output --var nat_public_ip

        # Refresh a statefile (no longer part of plan)
        kompos clusters/qe1.yaml terraform refresh

        # Taint a resource- forces a destroy, then recreate on next plan/apply
        kompos clusters/qe1.yaml terraform taint --module vpc --resource aws_instance.nat

        # Untaint a resource
        kompos clusters/qe1.yaml terraform untaint --module vpc --resource aws_instance.nat

        # Show the statefile in human-readable form
        kompos clusters/qe1.yaml terraform show

        # Show the plan in human-readable form
        kompos clusters/qe1.yaml terraform show --plan

        # View parsed jinja on the terminal
        kompos clusters/qe1.yaml terraform template

        # Import an unmanaged existing resource to a statefile
        kompos clusters/qe1.yaml terraform import --module vpc --resource aws_instance.nat --name i-abcd1234

        # Use the Terraform Console on a cluster
        kompos clusters/qe1.yaml terraform console

        # Validate the syntax of Terraform files
        kompos clusters/qe1.yaml terraform validate

        # Specify which terraform path to use
        kompos clusters/qe1.yaml terraform plan --path-name terraformFolder1

        # Run terraform v2 integration
        kompos data/env=dev/region=va6/project=ee/cluster=experiments terraform plan
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
        validate_terraform_version(self.kompos_config.terraform_version())
        logger.info("Found extra_args %s", extra_args)

        reverse = ("destroy" == args.subcommand)
        composition_order = self.kompos_config.terraform_composition_order()
        detected_type, compositions = get_compositions(self.config_path, composition_order,
                                                       comp_type="terraform", reverse=reverse)

        return self.run_compositions(args, extra_args, compositions)

    def get_composition_path(self, args, cloud_type, raw_config):
        # Use the default local repo (not versioned).
        path = os.path.join(
            self.kompos_config.terraform_local_path(),
            self.kompos_config.terraform_root_path(),
            cloud_type,
        )

        # Overwrite with the nix output, if the nix integration is enabled.
        if is_nix_enabled(args, self.kompos_config.nix()):
            pname = self.kompos_config.terraform_repo_name()

            nix_install(
                pname,
                self.kompos_config.terraform_repo_url(),
                get_value_or(raw_config, 'infrastructure/terraform/version', 'master'),
                get_value_or(raw_config, 'infrastructure/terraform/sha256'),
            )

            # Nix store is read-only, and terraform doesn't work properly outside
            # of the module directory, so as a workaround we're using a temporary directory
            # with the contents of the derivation so terraform can create new files.
            # See: https://github.com/hashicorp/terraform/issues/18030
            path = os.path.join(
                writeable_nix_out_path(pname),
                self.kompos_config.terraform_root_path(),
                cloud_type,
            )

        return path

    def run_compositions(self, args, extra_args, compositions):

        for composition in compositions:
            logger.info("Running composition: %s", composition)

            # Check if composition has a complete path
            composition_path = self.config_path
            if composition not in composition_path:
                composition_path = self.config_path + "/terraform=" + composition

            filtered_output_keys = self.kompos_config.filtered_output_keys(composition)
            excluded_config_keys = self.kompos_config.excluded_config_keys(composition)
            pre_config_generator = PreConfigGenerator(excluded_config_keys, filtered_output_keys)
            raw_config = pre_config_generator.pre_generate_config(composition_path, composition)
            cloud_type = raw_config["cloud"]["type"]

            config_destination = self.get_composition_path(args, cloud_type, raw_config)

            parser = ConfigRunner.get_parser(argparse.ArgumentParser())
            if args.himl_args:
                himl_args = parser.parse_args(args.himl_args.split())
                logger.info("Extra himl arguments: %s", args.himl_args.split())
            else:
                himl_args = parser.parse_args([])

            # Generate configs
            tf_config_generator = TerraformConfigGenerator(excluded_config_keys, filtered_output_keys)
            tf_config_generator.generate_configs(himl_args, composition_path, config_destination, composition)

            # Run terraform
            return_code = self.execute(
                self.run_terraform(args, extra_args, config_destination, composition)
            )

            if return_code != 0:
                logger.error(
                    "Command finished with nonzero exit code for composition '%s'."
                    "Will skip remaining compositions.", composition
                )
                return return_code

        return return_code

    def run_terraform(self, args, extra_args, terraform_path, composition):
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

    def generate_configs(self, himl_args, config_path, config_destination, composition):
        config_path = get_config_path(config_path, composition)
        config_destination = get_composition_path(config_destination, composition)

        self.provider_config(himl_args, config_path, config_destination)
        self.variables_config(himl_args, config_path, config_destination)

    def provider_config(self, himl_args, config_path, composition_path):
        output_file = os.path.join(composition_path, TERRAFORM_PROVIDER_FILENAME)
        logger.info('Generating terraform config %s', output_file)

        filters = self.kompos_config.filtered_output_keys.copy() + ["provider", "terraform"]

        excluded = self.kompos_config.excluded_config_keys.copy()
        if himl_args.exclude:
            excluded = self.kompos_config.excluded_config_keys.copy() + himl_args.exclude

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

        excluded = self.kompos_config.excluded_config_keys.copy() + ["helm", "provider"]
        filtered = self.kompos_config.filtered_output_keys.copy()

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


def validate_terraform_version(expected_version):
    """
    Check if the terraform binary version is compatible with the
    version specified by the kompos configuration.
    """
    try:
        execution = Popen(['terraform', '--version'],
                          stdin=PIPE,
                          stdout=PIPE,
                          stderr=PIPE)
    except Exception:
        logging.exception("Terraform does not appear to be installed, "
                          "please ensure terraform is in your PATH")
        exit(1)

    current_version, execution_error = execution.communicate()
    current_version = current_version.decode('utf-8').replace(
        'Terraform ', '').split('\n', 1)[0]

    if expected_version == 'latest':
        return current_version

    if current_version != expected_version and execution.returncode == 0:
        raise Exception("Terraform should be %s, but you have %s. Please change your version."
                        % (expected_version, current_version)
                        )

    return current_version
