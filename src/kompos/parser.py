# Copyright 2019 Adobe. All rights reserved.
# This file is licensed to you under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License. You may obtain a copy
# of the License at http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software distributed under
# the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR REPRESENTATIONS
# OF ANY KIND, either express or implied. See the License for the specific language
# governing permissions and limitations under the License.

import argparse
import sys

from kompos import __version__
from kompos.helpers import print_error


class KomposArgumentParser(argparse.ArgumentParser):
    """Custom ArgumentParser with better error messages."""
    
    def error(self, message):
        """Override error to provide cleaner, more helpful messages."""
        # Extract just the essential error message
        if 'required: subcommand' in message.lower() or 'invalid choice' in message.lower():
            runner_name = self.prog.split()[-1] if len(self.prog.split()) > 1 else 'unknown'
            
            # Try to extract choices from the parser (check both subparsers and regular arguments with choices)
            choices = []
            for action in self._actions:
                if isinstance(action, argparse._SubParsersAction):
                    choices = list(action.choices.keys()) if action.choices else []
                    break
                elif hasattr(action, 'choices') and action.choices and action.dest in ('subcommand', 'command'):
                    choices = list(action.choices)
                    break
            
            if choices:
                print_error(f"Missing or invalid subcommand for '{runner_name}'")
                print("", file=sys.stderr)
                print(f"Available commands: {', '.join(choices)}", file=sys.stderr)
                print("", file=sys.stderr)
                print(f"Usage: kompos <config_path> {runner_name} {{{','.join(choices)}}}", file=sys.stderr)
            else:
                print_error(f"Missing required subcommand for '{runner_name}'")
                print("", file=sys.stderr)
                print(f"Run 'kompos <config_path> {runner_name} --help' to see available commands.", file=sys.stderr)
        else:
            print_error(message)
            print("", file=sys.stderr)
            self.print_usage(sys.stderr)
        sys.exit(2)


class RootParser:
    def __init__(self, sub_parsers=None):
        """
        :type sub_parsers: list[SubParserConfig]
        """

        if sub_parsers is None:
            sub_parsers = []
        self.sub_parsers = sub_parsers

    def _get_parser(self):
        parser = KomposArgumentParser(
            description='Run commands against a definition', prog='kompos')
        parser.add_argument('config_path',
                            type=str,
                            help='The config path from where to run compositions or generate a flat config file.')
        parser.add_argument('--root-path',
                            type=str,
                            help='The root of the resource tree it can be an absolute path or relative to the current dir')
        parser.add_argument('--verbose', '-v', action='count',
                            help='Get more verbose output from commands')
        parser.add_argument('--version',
                            action='version',
                            version=f'%(prog)s v{__version__}'
                            )
        parser.add_argument('--himl',
                            action='store',
                            dest='himl_args',
                            default=None,
                            help='for passing arguments to himl'
                                 '--himl="--arg1 --arg2" any himl argument is supported wrapped in quotes')
        subparsers = parser.add_subparsers(dest='command', parser_class=KomposArgumentParser)

        for subparser_conf in self.sub_parsers:
            subparser_instance = subparsers.add_parser(subparser_conf.get_name(),
                                                       help=subparser_conf.get_help(),
                                                       epilog=subparser_conf.get_epilog(),
                                                       formatter_class=subparser_conf.get_formatter())
            subparser_conf.configure(subparser_instance)

        return parser

    @staticmethod
    def _check_args_for_unicode(args):
        if args is None:
            args = sys.argv
        try:
            for value in args:
                value.encode('utf-8')
        except UnicodeDecodeError as e:
            print(
                f'Invalid character in argument "{e.args[1]}", most likely an "en dash", replace it with normal dash -')
            raise

    def parse_args(self, args=None):
        RootParser._check_args_for_unicode(args)
        return self._get_parser().parse_args(args)

    def parse_known_args(self, args=None):
        RootParser._check_args_for_unicode(args)
        return self._get_parser().parse_known_args(args)


class SubParserConfig:
    def get_name(self):
        pass

    def configure(self, parser):
        """
        Configure parser arguments for this runner.
        
        Override this method to add runner-specific arguments.
        Call self.add_himl_arguments(parser) to add standard HIML arguments.
        
        Args:
            parser: The argument parser to configure
        
        Returns:
            The configured parser
        """
        pass

    def get_formatter(self):
        return argparse.RawDescriptionHelpFormatter

    def get_help(self):
        return ""

    def get_epilog(self):
        return ""
    
    def add_himl_arguments(self, parser):
        """
        Helper to add all HIML arguments to the parser.
        
        Call this from your configure() method if your runner needs HIML args.
        Most runners that call generate_config() will need this.
        
        Args:
            parser: The argument parser to add HIML arguments to
        
        Returns:
            The parser with HIML arguments added
        
        Example:
            def configure(self, parser):
                parser.add_argument('--my-flag', help='My custom flag')
                self.add_himl_arguments(parser)  # Add standard HIML args
                return parser
        """
        from himl import ConfigRunner
        return ConfigRunner().get_parser(parser)
