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
from kompos.helpers import print_error
from . import Executor
from .komposconfig import KomposConfig
from .runner import GenericRunner
from .runners.config import ConfigRenderParserConfig, ConfigRenderRunner
from .runners.explore import ExploreParserConfig, ExploreRunner
from .runners.helmfile import HelmfileParser, HelmfileRunner
from .runners.terraform import TerraformParser, TerraformRunner
from .runners.tfe import TFEParserConfig, TFERunner
from .runners.validate import ValidateParserConfig, ValidateRunner

logger = logging.getLogger(__name__)


class DebugBufferHandler(logging.Handler):
    """Capture all log messages for error context"""

    def __init__(self):
        super().__init__()
        self.buffer = []
        self.max_lines = 200  # Keep last 200 lines

    def emit(self, record):
        try:
            msg = self.format(record)
            self.buffer.append(msg)
            # Keep only last N lines
            if len(self.buffer) > self.max_lines:
                self.buffer.pop(0)
        except Exception:
            self.handleError(record)

    def get_buffer(self):
        return '\n'.join(self.buffer)

    def clear(self):
        self.buffer.clear()


# Global debug buffer
_debug_buffer = DebugBufferHandler()
_debug_buffer.setFormatter(logging.Formatter('%(levelname)s:%(name)s:%(message)s'))


def configure_logging(args):
    if args.verbose:
        if args.verbose > 1:
            # -vv: Show everything including himl debug
            logging.basicConfig(level=logging.DEBUG)
        else:
            # -v: Show INFO but suppress verbose himl logs
            logging.basicConfig(level=logging.INFO)
            logging.getLogger('himl.config_generator').setLevel(logging.WARNING)
    else:
        # No -v: Show INFO for kompos, suppress himl
        logging.basicConfig(level=logging.INFO)
        logging.getLogger('himl.config_generator').setLevel(logging.WARNING)

    # Always attach debug buffer to capture everything
    root_logger = logging.getLogger()
    root_logger.addHandler(_debug_buffer)


class AppContainer(Container):
    def __init__(self, argv=None):
        super(AppContainer, self).__init__()
        # Configure runners
        self.generic_runner = auto(GenericRunner)
        self.terraform_runner = auto(TerraformRunner)
        self.helmfile_runner = auto(HelmfileRunner)
        self.config_runner = auto(ConfigRenderRunner)
        self.explore_runner = auto(ExploreRunner)
        self.tfe_runner = auto(TFERunner)
        self.validate_runner = auto(ValidateRunner)

        # Configure parsers
        self.root_parser = auto(RootParser)
        parsers = ListInstanceProvider()
        parsers.add(auto(TerraformParser))
        parsers.add(auto(HelmfileParser))
        parsers.add(auto(ConfigRenderParserConfig))
        parsers.add(auto(ExploreParserConfig))
        parsers.add(auto(TFEParserConfig))
        parsers.add(auto(ValidateParserConfig))
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
        logger.debug(f'cli args: {args}, extra_args: {extra_args}')

        # Bind some very useful dependencies
        self.package_dir = lambda c: os.path.dirname(__file__)
        self.console_args = cache(instance(args))
        self.console_extra_args = cache(instance(extra_args))
        self.command = lambda c: self.console_args.command
        self.root_path = cache(lambda c: get_root_path(c.console_args))
        self.config_path = cache(lambda c: get_config_path(c.console_args))

        # change path to the root_path
        logger.debug(f'root path: {self.root_path}')
        os.chdir(self.root_path)

        return args

    def run(self):
        # Check if command was provided
        if not self.console_args.command:
            print_error("No command specified")
            print("", file=sys.stderr)
            print("Available commands: tfe, terraform, helmfile, explore, validate, config", file=sys.stderr)
            print("", file=sys.stderr)
            print("Usage: kompos <config_path> <command> [options]", file=sys.stderr)
            print("", file=sys.stderr)
            print("Examples:", file=sys.stderr)
            print("  kompos configs/cloud=aws/.../composition=cluster tfe generate", file=sys.stderr)
            print("  kompos configs/cloud=aws/.../composition=account tfe generate", file=sys.stderr)
            print("  kompos configs/.../composition=cluster explore trace --key vpc.cidr", file=sys.stderr)
            print("", file=sys.stderr)
            print("Run 'kompos --help' for more information.", file=sys.stderr)
            sys.exit(1)
        
        command_name = f'{self.console_args.command}_runner'
        
        try:
            runner_instance = self.get_instance(command_name)
        except Exception as e:
            if "is not defined" in str(e):
                print_error(f"Unknown command: {self.console_args.command}")
                print("", file=sys.stderr)
                print("Available commands: tfe, terraform, helmfile, explore, validate, config", file=sys.stderr)
                print("", file=sys.stderr)
                print("Run 'kompos --help' for more information.", file=sys.stderr)
                sys.exit(1)
            raise

        if not os.path.isdir(self.config_path):
            print_error(f"Invalid composition path: {self.config_path}", 
                       "Composition path must be a valid directory.")
            sys.exit(1)

        try:
            return runner_instance.run(self.console_args, self.console_extra_args)
        except Exception as e:
            error_msg = str(e)
            error_type = type(e).__name__
            
            # Handle interpolation errors
            is_interpolation_error = "Interpolation could not be resolved" in error_msg and "{{" in error_msg
            
            # Handle type errors from nested key access on strings
            is_type_error = (error_type == 'TypeError' and 
                           'string indices must be integers' in error_msg)
            
            # Handle YAML syntax errors
            is_yaml_error = error_type == 'ConstructorError' and 'unhashable key' in error_msg

            if is_interpolation_error:
                # Show error message first (in red)
                from termcolor import colored
                sys.stdout.write("\n")
                sys.stdout.write(colored("=" * 80, 'red') + "\n")
                sys.stdout.write(colored("ERROR: " + error_msg, 'red', attrs=['bold']) + "\n")
                sys.stdout.write(colored("=" * 80, 'red') + "\n")
                sys.stdout.write("\n")
                sys.stdout.flush()

                # Then run auto-debug analysis (this adds more logs to buffer)
                self._handle_interpolation_error(e)

                # Exit cleanly (no traceback)
                sys.exit(1)
            elif is_type_error:
                # Show helpful error for type mismatches in interpolation
                from termcolor import colored
                print_error("Interpolation type error: Trying to access nested key on a string value")
                print("", file=sys.stderr)
                print("This usually means:", file=sys.stderr)
                print("  • You're accessing 'foo.bar.baz' but 'foo.bar' is a string, not a dict", file=sys.stderr)
                print("  • Check your config hierarchy for the interpolation path", file=sys.stderr)
                print("", file=sys.stderr)
                print(f"Use 'kompos {self.config_path} explore trace --key <key>' to debug", file=sys.stderr)
                sys.exit(1)
            elif is_yaml_error:
                # Handle YAML syntax errors
                self._handle_yaml_error(e)
                sys.exit(1)
            else:
                # For other errors, raise normally (with traceback)
                raise

    def _handle_interpolation_error(self, error):
        """
        Centralized handler for interpolation errors.
        Automatically runs debug analysis when himl interpolation fails.
        """
        import re

        error_msg = str(error)
        if "Interpolation could not be resolved" not in error_msg or "{{" not in error_msg:
            return  # Not an interpolation error

        # Extract unresolved interpolation
        match = re.search(r'{{[^}]+}}', error_msg)
        unresolved = match.group(0) if match else None

        if not unresolved:
            return

        # Try to run automatic debug analysis
        try:
            # Create explore runner instance
            explore = ExploreRunner(
                kompos_config=self.kompos_config,
                config_path=self.config_path,
                execute=False
            )

            # Determine excluded keys based on command and composition type
            excluded_keys = self._get_excluded_keys_from_error(error_msg)

            # If no keys found from error (logs were suppressed), get from komposconfig
            if not excluded_keys:
                # Extract composition type from config path
                import re
                comp_match = re.search(r'composition=(\w+)', self.config_path)
                if comp_match:
                    comp_type = comp_match.group(1)
                    # Get excluded keys directly from komposconfig dict
                    excluded_keys = (self.kompos_config.config
                                     .get('compositions', {})
                                     .get('config_keys', {})
                                     .get('excluded', {})
                                     .get(comp_type, []))

            # Run interpolation analysis
            analysis = explore.analyze_interpolation(
                config_path=self.config_path,
                raw_config=None,  # Will search filesystem instead
                interpolation=unresolved,
                excluded_keys=excluded_keys
            )

            # Display simplified, focused error
            if analysis and analysis.get('unresolved'):
                output_text = explore._format_as_text(analysis)
                # Write directly to stdout to avoid any logger formatting
                sys.stdout.write("\n")
                sys.stdout.write("!" * 80 + "\n")
                sys.stdout.write("! AUTO-DEBUG: Analyzing interpolation error...\n")
                sys.stdout.write("!" * 80 + "\n")
                sys.stdout.write(output_text)
                sys.stdout.write("\n")
                sys.stdout.flush()

        except Exception as debug_error:
            logger.debug(f"Could not run debug analysis: {debug_error}", exc_info=True)

    def _handle_yaml_error(self, error):
        """
        Handler for YAML syntax errors with helpful guidance.
        """
        import re
        from termcolor import colored
        
        error_msg = str(error)
        
        # Extract file and line number
        file_match = re.search(r'in "([^"]+)", line (\d+)', error_msg)
        if file_match:
            yaml_file = file_match.group(1)
            line_num = int(file_match.group(2))
            
            print_error("YAML syntax error in config file")
            print("", file=sys.stderr)
            print(f"File: {yaml_file}", file=sys.stderr)
            print(f"Line: {line_num}", file=sys.stderr)
            
            if 'unhashable key' in error_msg:
                print("", file=sys.stderr)
                print(colored("╭─ Likely Cause " + "─" * 63 + "╮", 'yellow'), file=sys.stderr)
                print(colored("│ Unquoted interpolation starting with {{ or {              │", 'yellow'), file=sys.stderr)
                print(colored("│                                                             │", 'yellow'), file=sys.stderr)
                print(colored("│ ✗ BAD:  foo: {{bar.baz}}                                   │", 'yellow'), file=sys.stderr)
                print(colored("│ ✓ GOOD: foo: \"{{bar.baz}}\"                                 │", 'yellow'), file=sys.stderr)
                print(colored("╰─" + "─" * 77 + "╯", 'yellow'), file=sys.stderr)
            
            # Try to show context from file
            try:
                with open(yaml_file, 'r') as f:
                    lines = f.readlines()
                    start = max(0, line_num - 3)
                    end = min(len(lines), line_num + 2)
                    
                    print("", file=sys.stderr)
                    print("Content around the error:", file=sys.stderr)
                    for i in range(start, end):
                        line_prefix = colored(f"  {i+1:3d}: ", 'dim')
                        line_content = lines[i].rstrip()
                        
                        if i + 1 == line_num:
                            # Highlight the error line
                            print(colored(f"► {i+1:3d}: {line_content}", 'red', attrs=['bold']), file=sys.stderr)
                        else:
                            print(f"{line_prefix}{line_content}", file=sys.stderr)
            except Exception as read_error:
                logger.debug(f"Could not read file for context: {read_error}")
        else:
            print_error(f"YAML error: {error_msg}")

    def _get_excluded_keys_from_error(self, error_msg):
        """Extract excluded keys from himl output in error context"""
        excluded = []
        for line in error_msg.split('\n'):
            if 'Excluding key' in line:
                # Parse "INFO:himl.config_generator:Excluding key workspaces"
                parts = line.split('Excluding key')
                if len(parts) > 1:
                    key = parts[1].strip()
                    excluded.append(key)
        return excluded


def run(args=None):
    """ App entry point """
    app_container = AppContainer(args)
    sys.exit(app_container.run())


def get_config_path(console_args):
    config_path = console_args.config_path

    # If a file was provided (e.g., from tab completion), use its parent directory
    if os.path.isfile(config_path):
        config_path = os.path.dirname(config_path)
        logger.debug(f"Config path is a file, using parent directory: {config_path}")

    if not os.path.isdir(config_path):
        print_error(f"Config path does not exist: {config_path}")
        # Check if path looks like it might be valid but we're in wrong directory
        if '/' in config_path and not config_path.startswith('/'):
            print("This is a relative path. Are you in the correct directory?", file=sys.stderr)
            print(f"Current directory: {os.getcwd()}", file=sys.stderr)
        sys.exit(1)

    return config_path


def get_root_path(args):
    """ Either the root_path option or the current working dir """
    if args.root_path:
        root_path = os.path.realpath(args.root_path)
        if not os.path.isdir(root_path):
            print_error(f"Root directory does not exist: {root_path}")
            sys.exit(1)
        return root_path

    return os.path.realpath(os.getcwd())
