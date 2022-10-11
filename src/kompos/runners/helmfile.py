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

from kubeconfig import KubeConfig

from kompos.parser import SubParserConfig
from kompos.runner import GenericRunner

logger = logging.getLogger(__name__)

RUNNER_TYPE = "helmfile"
RUNNER_REVERSE_COMPOSITION_CMD = "delete"
# The filename of the generated hierarchical configuration for Helmfile.
HELMFILE_VARIABLES_FILENAME = "generated-values.yaml"


class HelmfileParser(SubParserConfig):
    def get_name(self):
        return RUNNER_TYPE

    def get_help(self):
        return 'Wrap common helmfile tasks using hierarchical configuration support'

    def configure(self, parser):
        parser.add_argument('subcommand', help='One of the helmfile commands', type=str)

        return parser

    def get_epilog(self):
        return '''
        Examples:
            # Run helmfile sync
            kompos data/env=dev/region=va6/project=ee/cluster=experiments/composition=helmfile helmfile sync
            # Run helmfile sync on a single composition
            kompos data/env=dev/region=va6/project=ee/cluster=experiments/composition=helmfile/helmfile=myhelmcomposition helmfile sync
            # Run helmfile sync for a single chart
            kompos data/env=dev/region=va6/project=ee/cluster=experiments/composition=helmfile helmfile --selector chart=nginx-controller sync
            # Run helmfile sync with concurrency flag
            kompos data/env=dev/region=va6/project=ee/cluster=experiments/composition=helmfile helmfile --selector chart=nginx-controller sync --concurrency=1
        '''


class HelmfileRunner(GenericRunner):
    def __init__(self, kompos_config, full_config_path, config_path, execute):
        super(HelmfileRunner, self).__init__(kompos_config, full_config_path, config_path, execute, RUNNER_TYPE)

    def run_configuration(self, args):
        self.ordered_compositions = True
        self.reverse = (RUNNER_REVERSE_COMPOSITION_CMD == args.subcommand)

    def execution_configuration(self, composition, config_path, default_output_path, raw_config,
                                filtered_keys, excluded_keys):

        self.setup_kube_config(raw_config)

        output_file = os.path.join(default_output_path, composition, HELMFILE_VARIABLES_FILENAME)
        logger.info('Generating helmfiles variables file %s', output_file)

        self.generate_config(config_path=config_path,
                             filters=filtered_keys,
                             exclude_keys=excluded_keys,
                             output_format="yaml",
                             output_file=output_file,
                             print_data=True)

    @staticmethod
    def execution(args, extra_args, default_output_path, composition, raw_config):
        helmfile_composition_path = os.path.join(default_output_path, composition)

        cmd = "cd {helmfile_path} && helmfile {subcommand} {extra_args}".format(
            helmfile_path=helmfile_composition_path,
            subcommand=args.subcommand,
            extra_args=' '.join(extra_args), )

        return dict(command=cmd)

    def setup_kube_config(self, data):
        if data['helm']['global']['cluster']['type'] == 'k8s':
            if all(k in data['helm']['global']['cluster']['kubeconfig'] for k in ("path", "context")):
                if os.path.isfile(data['helm']['global']['cluster']['kubeconfig']['path']):
                    logger.info('Using kubeconfig file: %s', data['helm']['global']['cluster']['kubeconfig']['path'])
                else:
                    logger.warning('kubeconfig file not found: %s',
                                   data['helm']['global']['cluster']['kubeconfig']['path'])
                    sys.exit(1)

                kubeconfig_abs_path = os.path.abspath(data['helm']['global']['cluster']['kubeconfig']['path'])
                conf = KubeConfig(kubeconfig_abs_path)
                conf.use_context(data['helm']['global']['cluster']['kubeconfig']['context'])
                os.environ['KUBECONFIG'] = kubeconfig_abs_path
                logger.info('Current context: %s', conf.current_context())
            else:
                logger.warning('path or context keys not found in helm.global.cluster.kubeconfig')
                sys.exit(1)

        elif data['helm']['global']['cluster']['type'] == 'eks':
            cluster_name = data['helm']['global']['fqdn']
            aws_profile = data['helm']['global']['aws']['profile']
            region = data['helm']['global']['region']['location']
            file_location = self.generate_eks_kube_config(cluster_name, aws_profile, region)
            os.environ['KUBECONFIG'] = file_location

        else:
            logger.warning('cluster type must be k8s or eks')
            sys.exit(1)

    def generate_eks_kube_config(self, cluster_name, aws_profile, region):
        file_location = self.get_tmp_file()
        cmd = "aws eks update-kubeconfig --name {} --profile {} --region {} --kubeconfig {}".format(
            cluster_name, aws_profile, region, file_location)

        return_code = self.execute(dict(command=cmd))
        if return_code != 0:
            raise Exception("Unable to generate EKS kube config. Exit code was {}".format(return_code))
        return file_location

    @staticmethod
    def get_tmp_file():
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            return tmp_file.name
