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

from simpledi import Container, auto, cache, instance, ListInstanceProvider

from kompos.parser import RootParser
from . import Executor
from .komposconfig import KomposConfig
from .runner import GenericRunner
from .runners.config import ConfigRenderParserConfig, ConfigRenderRunner
from .runners.helmfile import HelmfileParser, HelmfileRunner
from .runners.terraform import TerraformParser, TerraformRunner

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
        # Configure runners
        self.generic_runner = auto(GenericRunner)
        self.terraform_runner = auto(TerraformRunner)
        self.helmfile_runner = auto(HelmfileRunner)
        self.config_runner = auto(ConfigRenderRunner)

        # Configure parsers
        self.root_parser = auto(RootParser)
        parsers = ListInstanceProvider()
        parsers.add(auto(TerraformParser))
        parsers.add(auto(HelmfileParser))
        parsers.add(auto(ConfigRenderParserConfig))
        self.sub_parsers = parsers

        # Configure
        self.argv = instance(argv)
        self.configure()
        # bind the command executor
        self.execute = auto(Executor)

        # Set up kompos config
        self.kompos_config = cache(auto(KomposConfig))
        self.kompos_config.validate_version()
        self.kompos_config.vault_backend()

    def configure(self):
        args, extra_args = self.root_parser.parse_known_args(self.argv)

        configure_logging(args)
        logger.debug('cli args: {}, extra_args: {}'.format(args, extra_args))

        # Bind some very useful dependencies
        self.package_dir = lambda c: os.path.dirname(__file__)
        self.console_args = cache(instance(args))
        self.console_extra_args = cache(instance(extra_args))
        self.command = lambda c: self.console_args.command
        self.root_path = cache(lambda c: get_root_path(c.console_args))
        self.config_path = cache(lambda c: get_config_path(c.console_args))
        self.full_config_path = cache(lambda c: os.path.join(self.root_path, self.config_path))

        # change path to the root_path
        logger.info('root path: {}'.format(self.root_path))
        os.chdir(self.root_path)

        return args

    def run(self):
        command_name = '%s_runner' % self.console_args.command
        runner_instance = self.get_instance(command_name)

        if not os.path.isdir(self.config_path):
            raise Exception("Provide a valid composition path.")

        return runner_instance.run(self.console_args, self.console_extra_args)


def run(args=None):
    """ App entry point """
    app_container = AppContainer(args)
    sys.exit(app_container.run())


def get_config_path(console_args):
    if not os.path.isdir(console_args.config_path):
        raise Exception("Provide a dir config path.")
    return console_args.config_path


def get_full_config_path(root_path, console_args):
    """ Return config path + root_path if path is relative """
    if os.path.isabs(console_args.config_path):
        return console_args.config_path
    return os.path.join(root_path, console_args.config_path)


def get_root_path(args):
    """ Either the root_path option or the current working dir """
    if args.root_path:
        if not os.path.isdir(os.path.realpath(args.root_path)):
            raise ValueError(
                "Specified root dir {} does not exists".format(os.path.realpath(args.root_path)))

        return os.path.realpath(args.root_path)

    return os.path.realpath(os.getcwd())
