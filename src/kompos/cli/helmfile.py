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
import sys

from kompos.komposconfig import HELMFILE_CONFIG_FILENAME, get_value_or
from kompos.nix import nix_install, nix_out_path, writeable_nix_out_path
from kompos.cli.parser import SubParserConfig
from kompos.hierarchical.composition_config_generator import (
    HierarchicalConfigGenerator,
    CompositionSorter,
    get_config_path,
)

logger = logging.getLogger(__name__)


HELMFILE_COMPOSITION_NAME = 'helmfiles'


class HelmfileParserConfig(SubParserConfig):
    def get_name(self):
        return 'helmfile'

    def get_help(self):
        return 'Wrap common helmfile tasks using hierarchical configuration support'

    def configure(self, parser):
        parser.add_argument(
            '--helmfile-path',
            type=str,
            default=None,
            help='Dir to where helmfile.yaml is located')
        return parser

    def get_epilog(self):
        return '''
        Examples:
            # Run helmfile sync
            kompos data/env=dev/region=va6/project=ee/cluster=experiments/composition=helmfiles helmfile sync
            # Run helmfile sync for a single chart
            kompos data/env=dev/region=va6/project=ee/cluster=experiments/composition=helmfiles helmfile --selector chart=nginx-controller sync
            # Run helmfile sync with concurrency flag
            kompos data/env=dev/region=va6/project=ee/cluster=experiments/composition=helmfiles helmfile --selector chart=nginx-controller sync --concurrency=1
        '''


class HelmfileRunner(HierarchicalConfigGenerator):
    def __init__(self, kompos_config, cluster_config_path, execute):
        super(HelmfileRunner, self).__init__()
        logging.basicConfig(level=logging.INFO)
        self.kompos_config = kompos_config
        self.cluster_config_path = cluster_config_path
        self.execute = execute

    def run(self, args, extra_args):
        if not os.path.isdir(self.cluster_config_path):
            raise Exception("Provide a valid composition directory path.")

        compositions = CompositionSorter(
            self.kompos_config.helmfile_composition_order()
        ).get_sorted_compositions(self.cluster_config_path)

        if not compositions or compositions[0] != HELMFILE_COMPOSITION_NAME:
            raise Exception("No helmfiles compositions where detected in {}".format(self.cluster_config_path))

        # We're assuming local path by default.
        helmfile_path = os.path.join(
            self.kompos_config.helmfile_local_path(),
            self.kompos_config.helmfile_root_path(),
        )

        # Overwrite if CLI flag is set.
        if args.helmfile_path:
            helmfile_path = args.helmfile_path

        # Overwrite if nix is enabled.
        if args.nix:
            pname = self.kompos_config.helmfile_repo_name()

            raw_config = self.generate_config(
                config_path=get_config_path(self.cluster_config_path, 'helmfile'),
                filters=self.kompos_config.filtered_output_keys('helmfile'),
                exclude_keys = self.kompos_config.excluded_config_keys('helmfile')
            )

            nix_install(
                pname,
                self.kompos_config.helmfile_repo_url(),
                get_value_or(raw_config, 'infrastructure/helmfile/version', 'master'),
                get_value_or(raw_config, 'infrastructure/helmfile/sha256'),
            )

            # FIXME: Nix store is read-only, and helmfile configuration has a hardcoded path for
            # the generated config, so as a workaround we're using a temporary directory
            # with the contents of the derivation so helmfile can create the config file.

            helmfile_path = os.path.join(
                writeable_nix_out_path(pname),
                self.kompos_config.helmfile_root_path()
            )

        self.setup_kube_config(
            self.generate_helmfile_config(
                get_config_path(self.cluster_config_path, compositions[0]), helmfile_path
            )
        )

        return dict(command=self.get_helmfile_command(helmfile_path, extra_args))

    def setup_kube_config(self, data):
        if data['helm']['global']['clusterType'] == 'eks':
            cluster_name = data['helm']['global']['fqdn']
            aws_profile = data['helm']['global']['aws']['profile']
            region = data['helm']['global']['region']['location']
            file_location = self.generate_eks_kube_config(
                cluster_name, aws_profile, region)
            os.environ['KUBECONFIG'] = file_location
        else:
            logger.warning('currently only eks type clusters supported')
            sys.exit(1)

    def generate_eks_kube_config(self, cluster_name, aws_profile, region):
        file_location = self.get_tmp_file()
        cmd = "aws eks update-kubeconfig --name {} --profile {} --region {} --kubeconfig {}".format(cluster_name,
                                                                                                    aws_profile,
                                                                                                    region,
                                                                                                    file_location)
        return_code = self.execute(dict(command=cmd))
        if return_code != 0:
            raise Exception(
                "Unable to generate EKS kube config. Exit code was {}".format(return_code))
        return file_location

    @staticmethod
    def get_tmp_file():
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            return tmp_file.name

    def generate_helmfile_config(self, path, helmfile_path):
        output_file = os.path.join(helmfile_path, HELMFILE_CONFIG_FILENAME)
        logger.info('Generating helmfiles config %s', output_file)

        filtered_keys = self.kompos_config.filtered_output_keys(HELMFILE_COMPOSITION_NAME)
        excluded_keys = self.kompos_config.excluded_config_keys(HELMFILE_COMPOSITION_NAME)

        return self.generate_config(config_path=path,
                                    filters=filtered_keys,
                                    exclude_keys=excluded_keys,
                                    output_format="yaml",
                                    output_file=output_file,
                                    print_data=True)

    def get_helmfile_command(self, helmfile_path, extra_args):
        helmfile_args = ' '.join(extra_args)
        return "cd {helmfile_path} && helmfile {helmfile_args}".format(
            helmfile_path=helmfile_path,
            helmfile_args=helmfile_args)
