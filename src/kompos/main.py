# Copyright 2019 Adobe. All rights reserved.
# This file is licensed to you under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License. You may obtain a copy
# of the License at http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software distributed under
# the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR REPRESENTATIONS
# OF ANY KIND, either express or implied. See the License for the specific language
# governing permissions and limitations under the License.

import sys
import logging
import os

from simpledi import Container, auto, cache, instance, ListInstanceProvider

from .cli.config_generator import ConfigGeneratorParserConfig, ConfigGeneratorRunner
from .cli.parser import RootParser
from .cli.terraform import TerraformParserConfig, TerraformRunner
from .cli.helmfile import HelmfileParserConfig, HelmfileRunner
from . import Executor
from .komposconfig import KomposConfig

logger = logging.getLogger(__name__)


def configure_logging(args):
    if args.verbose:
        if args.verbose > 1:
            logging.basicConfig(level=logging.DEBUG)
        else:
            logging.basicConfig(level=logging.INFO)


class AppContainer(Container):
    def __init__(self, argv=None):
        super(AppContainer, self).__init__()

        self.argv = instance(argv)

        self.configure_parsers()

        self.kompos_config = cache(auto(KomposConfig))
        self.terraform_runner = auto(TerraformRunner)
        self.helmfile_runner = auto(HelmfileRunner)
        self.config_runner = auto(ConfigGeneratorRunner)

        # bind the command executor
        self.execute = auto(Executor)

        self.configure()
        self.kompos_config.validate_version()
        self.kompos_config.vault_backend()

    def configure_parsers(self):
        self.root_parser = auto(RootParser)

        parsers = ListInstanceProvider()
        parsers.add(auto(TerraformParserConfig))
        parsers.add(auto(HelmfileParserConfig))
        parsers.add(auto(ConfigGeneratorParserConfig))
        self.sub_parsers = parsers

    def configure(self):
        args, extra_args = self.root_parser.parse_known_args(self.argv)
        configure_logging(args)

        logger.debug('cli args: %s, extra_args: %s', args, extra_args)

        # Bind some very useful dependencies
        self.console_args = cache(instance(args))
        self.console_extra_args = cache(instance(extra_args))
        self.command = lambda c: self.console_args.command
        self.cluster_config_path = cache(
            lambda c: get_cluster_config_path(
                c.root_dir, c.console_args))
        self.root_dir = cache(lambda c: get_root_dir(c.console_args))
        self.package_dir = lambda c: os.path.dirname(__file__)

        # change path to the root_dir
        logger.info('root dir: %s', self.root_dir)
        os.chdir(self.root_dir)

        return args

    def run(self):
        command_name = '%s_runner' % self.console_args.command
        runner_instance = self.get_instance(command_name)

        return runner_instance.run(self.console_args, self.console_extra_args)


def run(args=None):
    """ App entry point """
    app_container = AppContainer(args)

    output = app_container.run()

    if isinstance(output, int):
        return output
    ret = app_container.execute(output)
    sys.exit(ret)


def get_cluster_config_path(root_dir, console_args):
    """ Return config path + root_dir if path is relative """

    if os.path.isabs(console_args.cluster_config_path):
        return console_args.cluster_config_path
    return os.path.join(root_dir, console_args.cluster_config_path)


def get_root_dir(args):
    """ Either the root_dir option or the current working dir """

    if args.root_dir:
        if not os.path.isdir(os.path.realpath(args.root_dir)):
            raise ValueError(
                "Specified root dir '%s' does not exists" %
                os.path.realpath(
                    args.root_dir))

        return os.path.realpath(args.root_dir)

    return os.path.realpath(os.getcwd())
