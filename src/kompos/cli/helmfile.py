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
from kompos.hierarchical.composition_helper import get_config_path, get_compositions, PreConfigGenerator, \
    get_composition_path
from kompos.hierarchical.config_generator import HierarchicalConfigGenerator
from kompos.komposconfig import HELMFILE_CONFIG_FILENAME, get_value_or
from kompos.nix import nix_install, writeable_nix_out_path, is_nix_enabled

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
            help='Dir where helmfile.yaml is located')
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
    def __init__(self, kompos_config, config_path, execute):
        super(HelmfileRunner, self).__init__()
        logging.basicConfig(level=logging.INFO)
        self.kompos_config = kompos_config
        self.config_path = config_path
        self.execute = execute

    def run(self, args, extra_args):
        if not os.path.isdir(self.config_path):
            raise Exception("Provide a valid composition directory path.")

        composition_order = self.kompos_config.helmfile_composition_order()
        compositions = get_compositions(self.config_path, composition_order, path_type="composition",
                                        composition_type="helmfile", reverse=False)

        return self.run_compositions(args, extra_args, compositions)

    def get_composition_path(self, args, raw_config):
        # We're assuming local path by default.
        path = os.path.join(
            self.kompos_config.helmfile_local_path(),
            self.kompos_config.helmfile_root_path(),
        )

        # Overwrite if nix is enabled.
        if is_nix_enabled(args, self.kompos_config.nix()):
            pname = self.kompos_config.helmfile_repo_name()

            nix_install(
                pname,
                self.kompos_config.helmfile_repo_url(),
                get_value_or(raw_config, 'infrastructure/helmfile/version', 'master'),
                get_value_or(raw_config, 'infrastructure/helmfile/sha256'),
            )

            # FIXME: Nix store is read-only, and helmfile configuration has a hardcoded path for
            # the generated config, so as a workaround we're using a temporary directory
            # with the contents of the derivation so helmfile can create the config file.

            path = os.path.join(
                writeable_nix_out_path(pname),
                self.kompos_config.helmfile_root_path()
            )

        return path

    def run_compositions(self, args, extra_args, compositions):

        for composition in compositions:
            composition_path = self.config_path + "/helmfile=" + composition
            logger.info("Running composition: %s", composition)

            filtered_output_keys = self.kompos_config.filtered_output_keys(composition)
            excluded_config_keys = self.kompos_config.excluded_config_keys(composition)
            pre_config_generator = PreConfigGenerator(excluded_config_keys, filtered_output_keys)
            raw_config = pre_config_generator.pre_generate_config(composition_path, composition)

            # Generate output paths for configs
            hf_composition_source = self.get_composition_path(args, raw_config)

            # Generate configs
            self.generate_helmfile_config(composition_path, hf_composition_source, composition, raw_config)
            self.setup_kube_config(raw_config)

            # Run helmfile
            return_code = self.execute(
                self.run_helmfile(extra_args, hf_composition_source, composition)
            )

            if return_code != 0:
                logger.error(
                    "Command finished with nonzero exit code for composition '%s'."
                    "Will skip remaining compositions.", composition
                )
                return return_code

            return return_code

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

    def generate_helmfile_config(self, composition_path, composition_source_path, composition, raw_config):
        config_path = get_config_path(composition_path, composition)
        composition_path = get_composition_path(composition_source_path, composition, raw_config)
        output_file = os.path.join(composition_path, HELMFILE_CONFIG_FILENAME)

        logger.info('Generating helmfiles config %s', output_file)

        filtered_keys = self.kompos_config.filtered_output_keys(HELMFILE_COMPOSITION_NAME)
        excluded_keys = self.kompos_config.excluded_config_keys(HELMFILE_COMPOSITION_NAME)

        return self.generate_config(config_path=config_path,
                                    filters=filtered_keys,
                                    exclude_keys=excluded_keys,
                                    output_format="yaml",
                                    output_file=output_file,
                                    print_data=True)

    def run_helmfile(self, extra_args, helmfile_path, composition):
        helmfile_composition_path = os.path.join(helmfile_path, composition)
        helmfile_args = ' '.join(extra_args)
        cmd = "cd {helmfile_path} && helmfile {helmfile_args}".format(
            helmfile_path=helmfile_composition_path, helmfile_args=helmfile_args)

        return dict(command=cmd)
