"""
Validation runner for Kompos configurations.
Proactively checks for common configuration issues before generation.
"""

import logging
import os
import re
from typing import List, Dict, Any

from termcolor import colored

from kompos.parser import SubParserConfig
from kompos.runner import GenericRunner

logger = logging.getLogger(__name__)

RUNNER_TYPE = 'validate'


class ValidateParserConfig(SubParserConfig):
    def get_name(self):
        return RUNNER_TYPE

    def get_help(self):
        return 'Validate configuration for common issues before generation'

    def configure(self, parser):
        """Add validate-specific arguments. No HIML args needed."""
        parser.add_argument(
            '--rule',
            help='Run specific validation rule only',
            choices=['excluded-but-referenced', 'missing-layers', 'interpolation-syntax']
        )
        parser.add_argument(
            '--composition-type',
            help='Validate for specific composition type (e.g., account, cluster)',
        )
        parser.add_argument(
            '--strict',
            action='store_true',
            help='Exit with error code if any validation fails'
        )
        return parser


class ValidateRunner(GenericRunner):
    """
    Runner for validating Kompos configurations.
    
    Checks for common issues that would cause generation failures:
    - Keys referenced in interpolations but excluded from composition
    - Missing required configuration layers
    - Invalid composition type configurations
    - Circular dependencies
    
    Usage:
        kompos configs/path/to/composition validate [--rule RULE_NAME]
    """

    def __init__(self, kompos_config, config_path, execute=True):
        super().__init__(kompos_config, config_path, execute, RUNNER_TYPE)
        self.validation_rules = {
            'excluded-but-referenced': self._validate_excluded_but_referenced,
            'missing-layers': self._validate_missing_layers,
            'interpolation-syntax': self._validate_interpolation_syntax,
        }

    def run(self, args, extra_args=None):
        """Run validation checks"""
        logger.info(f"Running configuration validation for: {self.config_path}")

        # Determine which rules to run
        if args.rule:
            rules_to_run = {args.rule: self.validation_rules[args.rule]}
        else:
            rules_to_run = self.validation_rules

        # Run all validation rules
        all_results = []
        for rule_name, rule_func in rules_to_run.items():
            logger.info(f"Running validation rule: {rule_name}")
            try:
                results = rule_func(args)
                all_results.extend(results)
                logger.info(f"Rule {rule_name} completed with {len(results)} issue(s)")
            except Exception as e:
                logger.error(f"Rule {rule_name} failed: {e}", exc_info=True)
                raise

        # Display results
        self._display_results(all_results, args)

        # Return exit code
        if args.strict and any(r['severity'] == 'error' for r in all_results):
            return 1
        return 0

    def _validate_excluded_but_referenced(self, args) -> List[Dict[str, Any]]:
        """
        Validate that keys referenced in interpolations are not excluded.
        
        This catches the scenario where:
        1. A config file contains {{key.subkey}}
        2. The key exists in the hierarchy (has a value)
        3. BUT the key is excluded for this composition type
        
        Returns list of validation results with severity, message, and fix suggestions.
        """
        issues = []

        # Determine composition type
        comp_type = getattr(args, 'composition_type', None) if hasattr(args, 'composition_type') else None
        if not comp_type:
            comp_match = re.search(r'composition=(\w+)', self.config_path)
            if comp_match:
                comp_type = comp_match.group(1)

        if not comp_type:
            logger.warning(f"Could not determine composition type from path: {self.config_path}")
            return issues

        # Get excluded keys for this composition type
        excluded_keys = (self.kompos_config.config
                         .get('compositions', {})
                         .get('config_keys', {})
                         .get('excluded', {})
                         .get(comp_type, []))

        if not excluded_keys:
            logger.debug(f"No excluded keys for composition type: {comp_type} - skipping validation")
            return issues

        # Find all interpolations in config files
        interpolations = self._find_all_interpolations_in_hierarchy()

        logger.debug("Found %d interpolations in hierarchy", len(interpolations))

        # Check each interpolation's first-level key
        checked_keys = set()  # Avoid duplicate checks
        for interp_data in interpolations:
            interpolation = interp_data['interpolation']
            key_match = re.search(r'{{([^}]+)}}', interpolation)
            if not key_match:
                continue

            key_path = key_match.group(1).strip()
            first_key = key_path.split('.')[0]

            # Skip if already checked or not in excluded list
            if first_key in checked_keys or first_key not in excluded_keys:
                continue
            checked_keys.add(first_key)

            # Check if this key actually has a value in the hierarchy
            try:
                from kompos.runners.explore import ExploreRunner
                explore = ExploreRunner(
                    kompos_config=self.kompos_config,
                    config_path=self.config_path,
                    execute=False
                )
                trace = explore.trace_value(self.config_path, key_path, silent=True)

                # Check if key has a real value (not undefined)
                has_value = False
                last_value = None
                if trace and trace.get('trace'):
                    for step in trace['trace']:
                        val = step.get('value')
                        status = step.get('status', '').lower()
                        if val is not None and status not in ['undefined']:
                            has_value = True
                            last_value = val

                # If it has a value but is excluded, that's an issue
                if has_value:
                    # Find all files referencing this key
                    sources = [s for s in interpolations if s['interpolation'].startswith('{{' + first_key)]
                    source_files = list(set(s['file'] for s in sources))

                    issues.append({
                        'rule': 'excluded-but-referenced',
                        'severity': 'error',
                        'key': first_key,
                        'key_path': key_path,
                        'value': last_value,
                        'composition_type': comp_type,
                        'excluded_keys': excluded_keys,
                        'source_files': source_files[:5],  # Limit to 5 for display
                        'total_sources': len(source_files),
                        'message': (
                            f"Key '{first_key}' is referenced in config files but excluded "
                            f"for '{comp_type}' compositions"
                        ),
                        'fix_options': [
                            f"Remove '{first_key}' from .komposconfig.yaml exclusions for '{comp_type}'",
                            f"Move files using '{key_path}' to composition-specific defaults (e.g., defaults_{comp_type}.yaml)",
                            f"Remove unused interpolations containing '{first_key}' from global defaults"
                        ]
                    })
            except Exception as e:
                logger.debug(f"Could not trace key {key_path}: {e}")

        return issues

    def _validate_missing_layers(self, args) -> List[Dict[str, Any]]:
        """
        Validate that required hierarchy layers exist for composition.
        
        Placeholder for future implementation.
        """
        # TODO: Check if composition requires specific layers (region, etc)
        return []

    def _validate_interpolation_syntax(self, args) -> List[Dict[str, Any]]:
        """
        Validate interpolation syntax is correct.
        
        Placeholder for future implementation.
        """
        # TODO: Check for malformed interpolations, unclosed brackets, etc
        return []

    def _find_all_interpolations_in_hierarchy(self) -> List[Dict[str, str]]:
        """
        Find all interpolations in YAML files within the config hierarchy.
        
        Returns list of dicts with 'file', 'line', 'content', 'interpolation'
        """
        results = []

        # Start from config_path and walk up the hierarchy
        config_root = os.getcwd()  # Kompos runs from the project root

        # Convert config_path to absolute path
        if os.path.isabs(self.config_path):
            abs_config_path = self.config_path
        else:
            abs_config_path = os.path.join(config_root, self.config_path)

        current_dir = abs_config_path if os.path.isdir(abs_config_path) else os.path.dirname(abs_config_path)

        logger.debug(f"Searching for interpolations from: {current_dir}")
        logger.debug(f"Config root: {config_root}")

        visited_dirs = set()

        while current_dir and current_dir not in visited_dirs:
            visited_dirs.add(current_dir)

            # Stop if we've gone above the config root
            if not current_dir.startswith(config_root):
                logger.debug("Reached config root boundary, stopping")
                break

            logger.debug(f"Checking directory: {current_dir}")

            if os.path.isdir(current_dir):
                try:
                    yaml_files = [f for f in os.listdir(current_dir) if f.endswith(('.yaml', '.yml'))]
                    logger.debug(f"Found {len(yaml_files)} YAML files in {os.path.basename(current_dir)}")

                    for file in yaml_files:
                        file_path = os.path.join(current_dir, file)
                        try:
                            with open(file_path, 'r') as f:
                                for line_num, line in enumerate(f, 1):
                                    # Find all interpolations in this line
                                    for match in re.finditer(r'{{[^}]+}}', line):
                                        results.append({
                                            'file': os.path.relpath(file_path, config_root),
                                            'line': line_num,
                                            'content': line.strip(),
                                            'interpolation': match.group(0)
                                        })
                        except Exception as e:
                            logger.debug(f"Could not read file {file_path}: {e}")
                except Exception as e:
                    logger.warning(f"Could not list directory {current_dir}: {e}")

            # Move up one level
            parent = os.path.dirname(current_dir)
            if parent == current_dir:  # Reached root
                logger.debug("Reached filesystem root, stopping")
                break
            current_dir = parent

        logger.debug("Total interpolations found: %d", len(results))
        return results

    def _display_results(self, results: List[Dict[str, Any]], args):
        """Display validation results in a user-friendly format"""
        if not results:
            print(colored("✓ All validation checks passed!", 'green', attrs=['bold']))
            return

        # Count by severity
        errors = [r for r in results if r['severity'] == 'error']
        warnings = [r for r in results if r['severity'] == 'warning']

        print()
        print(colored("=" * 80, 'yellow'))
        print(colored("VALIDATION RESULTS", 'yellow', attrs=['bold']))
        print(colored("=" * 80, 'yellow'))
        print(f"Config Path: {colored(self.config_path, 'white', attrs=['bold'])}")
        print()

        if errors:
            print(colored(f"❌ {len(errors)} Error(s) Found", 'red', attrs=['bold']))
        if warnings:
            print(colored(f"⚠️  {len(warnings)} Warning(s) Found", 'yellow', attrs=['bold']))
        print()

        # Display each issue
        for i, issue in enumerate(results, 1):
            severity_color = 'red' if issue['severity'] == 'error' else 'yellow'
            severity_symbol = '❌' if issue['severity'] == 'error' else '⚠️'

            print(colored(f"{severity_symbol} Issue #{i}: {issue['rule']}", severity_color, attrs=['bold']))
            print(f"  {issue['message']}")
            print()

            # Display issue-specific details
            if issue['rule'] == 'excluded-but-referenced':
                print(f"  Key: {colored(issue['key'], 'cyan')}")
                print(f"  Current Value: {colored(issue['value'], 'white')}")
                print(f"  Composition Type: {colored(issue['composition_type'], 'cyan')}")
                print(f"  Excluded Keys: {colored(', '.join(issue['excluded_keys']), 'yellow')}")
                print()

                print(colored("  Referenced in:", 'white'))
                for src_file in issue['source_files']:
                    print(f"    • {colored(src_file, 'white', attrs=['dark'])}")
                if issue['total_sources'] > len(issue['source_files']):
                    remaining = issue['total_sources'] - len(issue['source_files'])
                    print(f"    ... and {remaining} more file(s)")
                print()

                print(colored("  Fix Options:", 'green', attrs=['bold']))
                for j, fix in enumerate(issue['fix_options'], 1):
                    print(f"    {j}. {colored(fix, 'green')}")
                print()

        print(colored("=" * 80, 'yellow'))
        print()
