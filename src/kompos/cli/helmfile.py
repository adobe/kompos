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

from kompos.cli.parser import SubParserConfig
from kompos.helpers.composition_helper import get_config_path, get_compositions, get_composition_path, \
    get_raw_config, get_himl_args, get_output_path
from kompos.helpers.himl_helper import HierarchicalConfigGenerator
from kompos.helpers.runner_helper import validate_runner_version
from kompos.komposconfig import HELMFILE_CONFIG_FILENAME

logger = logging.getLogger(__name__)

RUNNER_TYPE = "helmfile"


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


class HelmfileRunner(HierarchicalConfigGenerator):
    def __init__(self, kompos_config, config_path, execute):
        super(HelmfileRunner, self).__init__()

        logging.basicConfig(level=logging.INFO)

        self.kompos_config = kompos_config
        self.config_path = config_path
        self.execute = execute

    def run(self, args, extra_args):
        # Stop processing if an incompatible version is detected.
        validate_runner_version(self.kompos_config, RUNNER_TYPE)

        if len(extra_args) > 1:
            logger.info("Found extra_args %s", extra_args)

        reverse = ("delete" == args.subcommand)
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
            config_destination = get_output_path(args, raw_config, self.kompos_config, RUNNER_TYPE)

            # Generate configs
            self.generate_helmfile_config(get_himl_args(args), composition_path, config_destination, composition)
            self.setup_kube_config(raw_config)

            # Run helmfile
            return_code = self.execute(self.run_helmfile(args, extra_args, config_destination, composition))

            if return_code != 0:
                logger.error(
                    "Command finished with nonzero exit code for composition '%s'."
                    "Will skip remaining compositions.", composition
                )
                return return_code

        return 0

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
            file_location = self.generate_eks_kube_config(
                cluster_name, aws_profile, region)
            os.environ['KUBECONFIG'] = file_location

        else:
            logger.warning('cluster type must be k8s or eks')
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

    def generate_helmfile_config(self, himl_args, config_path, config_destination, composition):
        config_path = get_config_path(config_path, composition)
        config_destination = get_composition_path(config_destination, composition)

        output_file = os.path.join(config_destination, HELMFILE_CONFIG_FILENAME)
        logger.info('Generating helmfiles config %s', output_file)

        filtered_keys = self.kompos_config.filtered_output_keys(composition)
        excluded_keys = self.kompos_config.excluded_config_keys(composition)

        if himl_args.exclude:
            filtered_keys = self.kompos_config.filtered_output_keys(composition) + himl_args.filter
            excluded_keys = self.kompos_config.excluded_config_keys(composition) + himl_args.exclude

        return self.generate_config(config_path=config_path,
                                    filters=filtered_keys,
                                    exclude_keys=excluded_keys,
                                    output_format="yaml",
                                    output_file=output_file,
                                    print_data=True)

    @staticmethod
    def run_helmfile(args, extra_args, helmfile_path, composition):
        helmfile_composition_path = os.path.join(helmfile_path, composition)

        cmd = "cd {helmfile_path} && helmfile {subcommand} {extra_args}".format(
            helmfile_path=helmfile_composition_path,
            subcommand=args.subcommand,
            extra_args=' '.join(extra_args),)

        return dict(command=cmd)
