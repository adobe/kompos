# Copyright 2019 Adobe. All rights reserved.
# This file is licensed to you under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License. You may obtain a copy
# of the License at http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software distributed under
# the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR REPRESENTATIONS
# OF ANY KIND, either express or implied. See the License for the specific language
# governing permissions and limitations under the License.

import os
import logging
import argparse
import json

from subprocess import Popen, PIPE

from himl.main import ConfigRunner
from kompos.nix import nix_install, nix_out_path, writeable_nix_out_path
from kompos.komposconfig import (
    TERRAFORM_CONFIG_FILENAME,
    TERRAFORM_PROVIDER_FILENAME,
    get_value_or,
    local_config_dir
)
from kompos.cli.parser import SubParserConfig
from kompos.hierarchical.composition_config_generator import (
    TerraformConfigGenerator,
    CompositionSorter,
    PreConfigGenerator,
    HierarchicalConfigGenerator,
    get_config_path,
)

logger = logging.getLogger(__name__)

# Terraform subcommands that will need re-initialization
SUBCMDS_WITH_INIT = [
    'apply',
    'destroy',
    'plan',
    'state'
]

# Terraform subcommands that use the variables file.
SUBCMDS_WITH_VARS = [
    'apply',
    'plan',
    'destroy'
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


class TerraformRunner():
    def __init__(self, root_dir, cluster_config_path, kompos_config, execute):
        self.cluster_config_path = cluster_config_path
        self.root_dir = root_dir
        self.kompos_config = kompos_config
        self.execute = execute

    def run(self, args, extra_args):
        if not os.path.isdir(self.cluster_config_path):
            raise Exception("Provide a valid composition directory path.")

        # Stop processing if an incompatible version is detected.
        validate_terraform_version(self.kompos_config.terraform_version())

        logger.info("Found extra_args %s", extra_args)
        return self.check_compositions(args, extra_args)

    def check_compositions(self, args, extra_args):
        logging.basicConfig(level=logging.INFO)
        all_compositions = self.kompos_config.terraform_composition_order()

        compositions = CompositionSorter(all_compositions) \
                           .get_sorted_compositions(
                                self.cluster_config_path, reverse=("destroy" == args.subcommand)
                           )
        if not compositions:
            raise Exception(
                "No terraform compositions were detected in {}.".format(self.cluster_config_path))

        return self.run_compositions(args, extra_args, self.cluster_config_path, compositions)

    def run_compositions(self, args, extra_args, config_path, compositions):
        return_code = 0

        for composition in compositions:
            logger.info("Running composition: %s", composition)

            filtered_output_keys = self.kompos_config.filtered_output_keys(composition)
            excluded_config_keys = self.kompos_config.excluded_config_keys(composition)
            tf_config_generator = TerraformConfigGenerator(excluded_config_keys, filtered_output_keys)
            pre_config_generator = PreConfigGenerator(excluded_config_keys, filtered_output_keys)

            raw_config = pre_config_generator.pre_generate_config(config_path, composition)
            cloud_type = raw_config["cloud"]["type"]

            # Use the default local repo (not versioned).
            terraform_composition_path = os.path.join(
                self.kompos_config.terraform_local_path(),
                self.kompos_config.terraform_root_path(),
                cloud_type,
            )

            # Overwrite with the nix output, if the nix integration is enabled.
            if args.nix:
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
                terraform_composition_path = os.path.join(
                    writeable_nix_out_path(pname),
                    self.kompos_config.terraform_root_path(),
                    cloud_type
                )

            parser = ConfigRunner.get_parser(argparse.ArgumentParser())

            if args.himl_args:
                himl_args = parser.parse_args(args.himl_args.split())
                logger.info("Extra himl arguments: %s", args.himl_args.split())
            else:
                himl_args = parser.parse_args(extra_args)

            tf_config_generator.generate_files(
                himl_args,
                config_path,
                terraform_composition_path,
                composition
            )

            return_code = self.execute(
                self.run_terraform(
                    args,
                    extra_args,
                    terraform_composition_path,
                    composition
                )
            )

            if return_code != 0:
                logger.error(
                    "Command finished with nonzero exit code for composition '%s'."
                    "Will skip remaining compositions.", composition
                )
                return return_code

        return return_code

    def run_terraform(self, args, extra_args, terraform_path, composition):
        terraform_path = os.path.join(terraform_path, composition)
        var_file = '-var-file="{}"'.format(TERRAFORM_CONFIG_FILENAME) if args.subcommand in SUBCMDS_WITH_VARS else ''

        terraform_env_config = 'export TF_PLUGIN_CACHE_DIR="{}"'.format(local_config_dir())

        cmd = "cd {terraform_path} && " \
              "{remove_local_cache} " \
              "{env_config} ; terraform init && terraform {subcommand} {tf_args} {extra_args} {var_file}".format(
                terraform_path=terraform_path,
                remove_local_cache=remove_local_cache_cmd(args.subcommand),
                subcommand=args.subcommand,
                extra_args=' '.join(extra_args),
                tf_args=' '.join(args.terraform_args),
                var_file=var_file,
                env_config=terraform_env_config
              )

        return dict(command=cmd, post_actions=[])


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
    except Exception as e:
        logging.exception("Terraform does not appear to be installed, "
                          "please ensure terraform is in your PATH")
        exit(1)

    current_version, execution_error = execution.communicate()
    current_version = current_version.decode('utf-8').replace(
        'Terraform ', '').split('\n', 1)[0]

    if expected_version == 'latest':
        return current_version

    if current_version != expected_version and execution.returncode == 0:
        raise Exception("Terraform should be %s, but you have %s. Please change your version."\
                        % (expected_version, current_version)
        )

    return current_version
