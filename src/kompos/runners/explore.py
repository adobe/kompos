# Copyright 2026 Adobe. All rights reserved.
# This file is licensed to you under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License. You may obtain a copy
# of the License at http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software distributed under
# the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR REPRESENTATIONS
# OF ANY KIND, either express or implied. See the License for the specific language
# governing permissions and limitations under the License.

import logging
import os
from typing import Dict, List, Any

from termcolor import colored

from kompos.parser import SubParserConfig
from kompos.runner import GenericRunner

logger = logging.getLogger(__name__)

RUNNER_TYPE = "explore"


class ExploreParserConfig(SubParserConfig):
    def get_name(self):
        return RUNNER_TYPE

    def get_help(self):
        return 'Explore hierarchical configuration distribution and data flow'

    def configure(self, parser):
        """Add explore-specific arguments and standard HIML arguments."""
        # Explore subcommand
        parser.add_argument('subcommand',
                            choices=['analyze', 'trace', 'visualize', 'compare', 'debug'],
                            help='Exploration mode: analyze=distribution, trace=provenance, visualize=diagram, compare=matrix, debug=unresolved interpolations')

        # Trace-specific options
        parser.add_argument('--key',
                            type=str,
                            help='Specific config key to trace (for trace command)')

        # Compare-specific options
        parser.add_argument('--keys',
                            type=str,
                            nargs='+',
                            help='Specific keys to compare (for compare command)')

        # Debug options
        parser.add_argument('--interpolation',
                            type=str,
                            help='Specific interpolation to debug (e.g., "{{region.name}}")')

        # Add HIML arguments (needed for generate_config() calls)
        self.add_himl_arguments(parser)
        return parser

    def get_epilog(self):
        return '''
        Examples:
        # Analyze variable distribution across hierarchy
        kompos data/ explore analyze
        
        # Trace specific variable origins and overrides
        kompos data/env=dev/cluster=cluster1 explore trace --key vpc.cidr_block
        
        # Generate visual diagram
        kompos data/ explore visualize --format dot --output-file flow.dot
        
        # Compare configs across environments
        kompos data/ explore compare --keys vpc.cidr_block cluster.size
        
        # Debug unresolved interpolation
        kompos data/composition=account explore debug --interpolation '{{region.name}}'
        '''


class ExploreRunner(GenericRunner):
    def __init__(self, kompos_config, config_path, execute):
        super(ExploreRunner, self).__init__(kompos_config, config_path, execute, RUNNER_TYPE)

    def run_configuration(self, args):
        self.validate_runner = False
        self.ordered_compositions = False
        self.reverse = False
        self.generate_output = False

    def execution_configuration(self, composition, config_path, default_output_path, raw_config,
                                filtered_keys, excluded_keys):
        args = self.himl_args

        # Route to appropriate analysis method
        if args.subcommand == 'analyze':
            result = self.analyze_distribution(config_path)
        elif args.subcommand == 'trace':
            if not args.key:
                logger.error("--key required for trace command")
                return
            result = self.trace_value(config_path, args.key)
        elif args.subcommand == 'visualize':
            result = self.visualize_hierarchy(config_path, args.output_format)
        elif args.subcommand == 'compare':
            result = self.compare_configs(config_path, args.keys)
        elif args.subcommand == 'debug':
            result = self.analyze_interpolation(config_path, raw_config, args.interpolation, excluded_keys)
        else:
            logger.error(f"Unknown subcommand: {args.subcommand}")
            return

        # Output results using HIML args
        # If no output file and no explicit format specified, default to text for readability
        # Check if format was explicitly provided by user (not just HIML default)
        output_format = args.output_format
        if not args.output_file and output_format == 'yaml':
            # User didn't specify format and no file, default to text for terminal
            output_format = 'text'

        self._output_results(result, args.output_file, output_format)

    def analyze_distribution(self, config_path: str) -> Dict[str, Any]:
        """
        Analyze variable distribution across hierarchy.
        Shows what variables are defined at each level.
        """
        logger.info(f"Analyzing configuration distribution from: {config_path}")

        # Discover all configuration layers in the hierarchy
        layers = self._discover_hierarchy_layers(config_path)

        distribution = {
            'summary': {
                'total_layers': len(layers),
                'config_path': config_path
            },
            'layers': []
        }

        previous_config = {}
        for layer_path in layers:
            # Generate config at this layer
            try:
                layer_config = self.generate_config(
                    config_path=layer_path,
                    skip_interpolation_validation=True,
                    skip_secrets=True,
                    silent=True  # Don't print commands during trace
                )
            except Exception as e:
                logger.warning(f"Failed to generate config for {layer_path}: {e}")
                continue

            # Analyze changes from previous layer
            new_vars = []
            overridden_vars = []
            unchanged_vars = []

            for key, value in self.flatten_dict(layer_config).items():
                if key not in previous_config:
                    new_vars.append(key)
                elif previous_config[key] != value:
                    overridden_vars.append(key)
                else:
                    unchanged_vars.append(key)

            layer_info = {
                'path': layer_path,
                'new_vars': sorted(new_vars),
                'overridden_vars': sorted(overridden_vars),
                'unchanged_vars': len(unchanged_vars),
                'total_vars': len(layer_config)
            }

            distribution['layers'].append(layer_info)
            previous_config = self.flatten_dict(layer_config)

        return distribution

    def trace_value(self, config_path: str, key: str, silent: bool = False) -> Dict[str, Any]:
        """
        Trace a specific variable through the hierarchy.
        Shows where it originates and how it's overridden.
        Supports both leaf values and dictionary keys.
        
        Args:
            config_path: Path to config being processed
            key: Key to trace (e.g., "cluster.name")
            silent: If True, suppress logging output
        """
        if not silent:
            logger.info(f"Tracing key '{key}' from: {config_path}")

        layers = self._discover_hierarchy_layers(config_path)
        trace = {
            'key': key,
            'config_path': config_path,
            'trace': [],
            'is_dict': False
        }

        # Track if we find any values and collect similar keys
        found_any_value = False
        found_as_dict = False
        similar_keys = set()

        for layer_path in layers:
            try:
                layer_config = self.generate_config(
                    config_path=layer_path,
                    skip_interpolation_validation=True,
                    skip_secrets=True,
                    silent=True  # Don't print commands during trace
                )

                # First check if key exists in raw config (before flattening)
                raw_value = self.get_nested_value(layer_config, key)

                # If it's a dictionary, handle it specially
                if isinstance(raw_value, dict):
                    found_as_dict = True
                    found_any_value = True
                    trace['is_dict'] = True

                    # Get keys in this dictionary
                    dict_keys = list(raw_value.keys())

                    # Determine status
                    status = 'undefined'
                    if not trace['trace']:
                        status = 'new'
                    else:
                        prev_keys = trace['trace'][-1].get('dict_keys', [])
                        if set(dict_keys) != set(prev_keys):
                            status = 'changed'
                        else:
                            status = 'unchanged'

                    trace['trace'].append({
                        'layer': layer_path,
                        'value': f"<dict with {len(dict_keys)} keys>",
                        'dict_keys': dict_keys,
                        'status': status
                    })
                    continue

                # Otherwise handle as flat key
                flat_config = self.flatten_dict(layer_config)
                value = flat_config.get(key, None)

                # Collect keys that start with our search key (for suggestions)
                if not found_any_value:
                    for k in flat_config.keys():
                        if k.startswith(key + '.'):
                            similar_keys.add(k)

                if value is not None:
                    found_any_value = True

                # Determine status
                status = 'undefined'
                if value is not None:
                    if not trace['trace'] or trace['trace'][-1]['value'] is None:
                        status = 'new'
                    elif trace['trace'][-1]['value'] != value:
                        # Check if it's interpolation progress or actual override
                        prev_value = str(trace['trace'][-1]['value'])
                        curr_value = str(value)

                        # Detect interpolation: same structure but with fewer {{ }} tokens
                        prev_has_interp = '{{' in prev_value
                        curr_has_interp = '{{' in curr_value

                        # Count interpolation tokens
                        prev_token_count = prev_value.count('{{')
                        curr_token_count = curr_value.count('{{')

                        # If both have tokens and current has fewer, it's interpolation progress
                        if prev_has_interp and curr_token_count < prev_token_count:
                            status = 'interpolated'
                        else:
                            status = 'overridden'
                    else:
                        status = 'unchanged'

                trace['trace'].append({
                    'layer': layer_path,
                    'value': value,
                    'prev_value': trace['trace'][-1]['value'] if trace['trace'] else None,
                    'status': status
                })
            except Exception as e:
                logger.warning(f"Failed to trace in {layer_path}: {e}")

        # Add suggestions if key not found but similar keys exist
        if not found_any_value and similar_keys:
            trace['suggestions'] = sorted(list(similar_keys))[:10]  # Top 10 suggestions
            trace[
                'note'] = f"Key '{key}' not found. It may be a dictionary. Try one of the suggested keys, or add --show-dict-keys to see dictionary structure."

        return trace

    def visualize_hierarchy(self, config_path: str, output_format: str = 'yaml') -> Dict[str, Any]:
        """
        Generate visual representation of config hierarchy.
        Supports text tree and GraphViz DOT format.
        """
        logger.info(f"Visualizing hierarchy from: {config_path}")

        layers = self._discover_hierarchy_layers(config_path)

        # Build hierarchy structure
        hierarchy = {
            'root': config_path,
            'layers': [],
            'layer_contributions': []  # Track which layers contribute how many vars
        }

        previous_config = {}
        for layer_path in layers:
            try:
                layer_config = self.generate_config(
                    config_path=layer_path,
                    skip_interpolation_validation=True,
                    skip_secrets=True,
                    silent=True  # Don't print commands during trace
                )

                flat_config = self.flatten_dict(layer_config)

                # Track what's new at this layer
                new_vars = []
                for key in flat_config.keys():
                    if key not in previous_config:
                        new_vars.append(key)

                # Count YAML files at this layer and track per-file contributions
                layer_files = []
                file_contributions = {}  # file_name -> {new: N, overridden: N, interpolated: N}

                if os.path.isdir(layer_path):
                    # Get config before this layer (parent context)
                    parent_path = os.path.dirname(layer_path) if '/' in layer_path else None
                    parent_config = {}
                    if parent_path:
                        try:
                            parent_config_obj = self.generate_config(
                                config_path=parent_path,
                                skip_interpolation_validation=True,
                                skip_secrets=True
                            )
                            parent_config = self.flatten_dict(parent_config_obj)
                        except:
                            parent_config = previous_config
                    else:
                        parent_config = previous_config

                    # Check each file individually
                    for item in os.listdir(layer_path):
                        if item.endswith('.yaml') or item.endswith('.yml'):
                            file_path = os.path.join(layer_path, item)
                            if os.path.isfile(file_path):
                                layer_files.append(item)

                                # Load just this file's config
                                try:
                                    import yaml
                                    with open(file_path, 'r') as f:
                                        file_data = yaml.safe_load(f) or {}
                                    file_flat = self.flatten_dict(file_data)

                                    # Count keys by type: new, overridden, interpolated
                                    new_keys = 0
                                    overridden_keys = 0
                                    interpolated_keys = 0

                                    for k, v in file_flat.items():
                                        if k not in parent_config:
                                            new_keys += 1
                                        elif parent_config[k] != v:
                                            # Value changed - is it interpolation or override?
                                            prev_val = str(parent_config[k])
                                            curr_val = str(v)

                                            prev_has_interp = '{{' in prev_val
                                            curr_has_interp = '{{' in curr_val
                                            prev_token_count = prev_val.count('{{')
                                            curr_token_count = curr_val.count('{{')

                                            if prev_has_interp and curr_token_count < prev_token_count:
                                                interpolated_keys += 1
                                            else:
                                                overridden_keys += 1

                                    file_contributions[item] = {
                                        'new': new_keys,
                                        'overridden': overridden_keys,
                                        'interpolated': interpolated_keys
                                    }
                                except Exception as e:
                                    logger.debug(f"Failed to analyze file {file_path}: {e}")
                                    file_contributions[item] = {'new': 0, 'overridden': 0, 'interpolated': 0}

                # Track contribution (only if this layer adds vars)
                delta = len(flat_config) - len(previous_config)
                if delta > 0:
                    hierarchy['layer_contributions'].append({
                        'path': layer_path,
                        'delta': delta,
                        'files': sorted(layer_files),
                        'file_contributions': file_contributions
                    })

                hierarchy['layers'].append({
                    'path': layer_path,
                    'depth': layer_path.count('/'),
                    'var_count': len(flat_config),
                    'new_vars': sorted(new_vars)[:5],  # Top 5 new vars for preview
                    'files': sorted(layer_files),  # Files at this layer
                    'file_contributions': file_contributions  # Per-file key counts
                })

                previous_config = flat_config
            except Exception as e:
                logger.warning(f"Failed to analyze {layer_path}: {e}")

        hierarchy['output_format'] = output_format
        return hierarchy

    def compare_configs(self, config_path: str, keys: List[str] = None) -> Dict[str, Any]:
        """
        Compare configurations across different paths.
        Shows value differences in a matrix format.
        """
        logger.info(f"Comparing configurations from: {config_path}")

        # Discover all leaf paths (actual deployable configs)
        leaf_paths = self._discover_leaf_paths(config_path)

        comparison = {
            'paths': leaf_paths,
            'keys': keys or [],
            'matrix': {}
        }

        # Generate config for each path
        configs = {}
        for path in leaf_paths:
            try:
                configs[path] = self.flatten_dict(
                    self.generate_config(
                        config_path=path,
                        skip_interpolation_validation=True,
                        skip_secrets=True
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to generate config for {path}: {e}")

        # Build comparison matrix
        # If keys specified, use those; otherwise find common keys
        if keys:
            compare_keys = keys
        else:
            # Find all keys across all configs
            all_keys = set()
            for config in configs.values():
                all_keys.update(config.keys())
            compare_keys = sorted(all_keys)

        for key in compare_keys:
            comparison['matrix'][key] = {}
            for path, config in configs.items():
                comparison['matrix'][key][path] = config.get(key, '(undefined)')

        return comparison

    def analyze_interpolation(self, config_path: str, raw_config: Dict[str, Any] = None,
                              interpolation: str = None, excluded_keys: List[str] = None) -> Dict[str, Any]:
        """
        Analyze unresolved interpolations in config generation.
        Traces back to source files and suggests fixes.
        
        Args:
            config_path: Path to config being processed
            raw_config: Optional generated config (if None, will only search filesystem)
            interpolation: Specific interpolation to search for (e.g., "{{region.name}}")
            excluded_keys: Keys excluded from generation
        
        Returns:
            Analysis results with source locations and suggestions
        """
        import re

        logger.info(f"Analyzing interpolations in: {config_path}")

        # Show helpful command for manual exploration
        if interpolation:
            unresolved_key = interpolation.strip('{}').strip()
            logger.info(
                f"TIP: For detailed value trace, run: kompos {config_path} explore trace --key {unresolved_key}")

        analysis = {
            'config_path': config_path,
            'unresolved': [],
            'excluded_keys': excluded_keys or []
        }

        # If specific interpolation provided, search for it
        if interpolation:
            unresolved_items = [interpolation]
        elif raw_config:
            # Scan raw_config for unresolved interpolations
            unresolved_items = self._find_unresolved_interpolations(raw_config)
        else:
            logger.warning("No interpolation specified and no raw_config provided")
            return analysis

        for unresolved in unresolved_items:
            # Extract the key being referenced
            key_match = re.search(r'{{([^}]+)}}', unresolved)
            key_path = key_match.group(1) if key_match else None

            # Find source files containing this interpolation
            sources = self._find_interpolation_sources(config_path, unresolved)

            # NEW: Add value trace for the key to show its evolution
            trace = None
            if key_path:
                try:
                    trace = self.trace_value(config_path, key_path, silent=True)
                except Exception as e:
                    logger.warning(f"Could not trace key {key_path}: {e}")

            # Determine likely causes (NOW with trace data!)
            causes = self._diagnose_interpolation_failure(unresolved, key_path, config_path, excluded_keys, trace)

            analysis['unresolved'].append({
                'interpolation': unresolved,
                'key_path': key_path,
                'sources': sources,
                'causes': causes,
                'trace': trace  # Include trace data
            })

        return analysis

    def _find_unresolved_interpolations(self, data: Any, path: str = '') -> List[str]:
        """Recursively find all unresolved interpolations in config data"""
        unresolved = []

        if isinstance(data, dict):
            for key, value in data.items():
                new_path = f"{path}.{key}" if path else key
                unresolved.extend(self._find_unresolved_interpolations(value, new_path))
        elif isinstance(data, list):
            for i, item in enumerate(data):
                unresolved.extend(self._find_unresolved_interpolations(item, f"{path}[{i}]"))
        elif isinstance(data, str) and '{{' in data:
            unresolved.append(data)

        return unresolved

    def _find_interpolation_sources(self, config_path: str, interpolation: str) -> List[Dict[str, Any]]:
        """Find all source files containing the interpolation"""
        import os

        sources = []

        # Walk up the directory tree to find all relevant YAML files
        current_dir = os.path.dirname(config_path) if os.path.isfile(config_path) else config_path
        visited_dirs = set()

        while current_dir and current_dir not in visited_dirs:
            visited_dirs.add(current_dir)

            if os.path.isdir(current_dir):
                for file in os.listdir(current_dir):
                    if file.endswith('.yaml') or file.endswith('.yml'):
                        file_path = os.path.join(current_dir, file)
                        try:
                            with open(file_path, 'r') as f:
                                content = f.read()
                                if interpolation in content:
                                    # Find line numbers
                                    lines = content.split('\n')
                                    for line_num, line in enumerate(lines, 1):
                                        if interpolation in line:
                                            sources.append({
                                                'file': file_path,
                                                'line': line_num,
                                                'content': line.strip()
                                            })
                        except Exception:
                            pass

            parent = os.path.dirname(current_dir)
            if parent == current_dir:
                break
            current_dir = parent

        return sources

    def _diagnose_interpolation_failure(self, interpolation: str, key_path: str,
                                        config_path: str, excluded_keys: List[str],
                                        trace: Dict[str, Any] = None) -> List[str]:
        """Diagnose why an interpolation might have failed"""
        import re

        causes = []

        # Extract first-level key
        if key_path:
            first_key = key_path.split('.')[0]

            # **NEW: Check if key exists but is excluded (the contradiction!)**
            if trace and trace.get('trace'):
                # Check if key has a REAL value in the trace (not undefined)
                last_value = None
                for step in trace['trace']:
                    val = step.get('value')
                    status = step.get('status', '').lower()
                    # Accept any value that's not None and status is not 'undefined'
                    if val is not None and status not in ['undefined']:
                        last_value = val

                # If it has a value BUT is excluded → ROOT CAUSE!
                if last_value is not None and first_key in (excluded_keys or []):
                    causes.append(
                        f"⚠️  ROOT CAUSE: Key '{first_key}' has value in config hierarchy "
                        f"('{last_value}') BUT is EXCLUDED from this composition. "
                        f"The key exists but gets removed before interpolation resolution."
                    )

                    # Extract composition type from path
                    comp_match = re.search(r'composition=(\w+)', config_path)
                    if comp_match:
                        comp_type = comp_match.group(1)
                        causes.append(
                            f"💡 FIX Option 1: Remove '{first_key}' from .komposconfig.yaml exclusions "
                            f"for '{comp_type}' compositions"
                        )
                        causes.append(
                            f"💡 FIX Option 2: Move files using '{key_path}' interpolation to composition-specific "
                            f"defaults (e.g., defaults_cluster.yaml instead of defaults_tags.yaml)"
                        )
                    return causes  # This is the root cause, show it first!

            # Check if it's excluded (original check, but now supplementary)
            elif first_key in (excluded_keys or []):
                causes.append(f"Key '{first_key}' is excluded from config generation")

            # Check if it's a hierarchy level that doesn't exist in path
            hierarchy_levels = ['region', 'cluster', 'vpc', 'account', 'node_groups']
            if first_key in hierarchy_levels:
                if f"{first_key}=" not in config_path:
                    causes.append(f"No '{first_key}' layer in config path - composition may be at wrong level")

            # Check for common mistakes
            if 'cluster' in key_path and 'composition=account' in config_path:
                causes.append("Account composition referencing cluster-specific config")

            if 'region' in key_path and 'composition=account' in config_path:
                causes.append("Account composition missing region layer (account resources still need default region)")

        # Check for nested interpolation issues
        if '{{' in interpolation.replace(interpolation[interpolation.find('{{'):interpolation.find('}}') + 2], '', 1):
            causes.append("Nested interpolation may not be fully resolved by himl")

        if not causes:
            causes.append("Key not defined in any layer of the config hierarchy")

        return causes

    def _discover_hierarchy_layers(self, config_path: str) -> List[str]:
        """
        Discover all hierarchy layers from root to specified path.
        Returns list of paths in order from root to leaf.
        """
        layers = []

        # Split path into segments
        segments = config_path.split('/')

        # Build cumulative paths
        current_path = ''
        for segment in segments:
            if segment:
                current_path = os.path.join(current_path, segment) if current_path else segment
                if os.path.isdir(current_path):
                    layers.append(current_path)

        return layers

    def _discover_leaf_paths(self, config_path: str) -> List[str]:
        """
        Discover all leaf configuration paths (actual deployable configs).
        Traverses directory tree to find deepest paths with config files.
        """
        leaf_paths = []

        def walk_path(path):
            if not os.path.isdir(path):
                return

            # Check if this directory has config files
            has_yaml = any(f.endswith('.yaml') or f.endswith('.yml')
                           for f in os.listdir(path) if os.path.isfile(os.path.join(path, f)))

            # Check for subdirectories
            subdirs = [d for d in os.listdir(path)
                       if os.path.isdir(os.path.join(path, d)) and not d.startswith('.')]

            if subdirs:
                # Recurse into subdirectories
                for subdir in subdirs:
                    walk_path(os.path.join(path, subdir))
            elif has_yaml:
                # Leaf directory with config
                leaf_paths.append(path)

        walk_path(config_path)
        return sorted(leaf_paths)

    def _highlight_diff(self, prev_value: str, curr_value: str) -> str:
        """
        Highlight the changed parts between two strings.
        Returns the current value with changed parts highlighted.
        """
        if prev_value is None or curr_value is None:
            return str(curr_value)

        prev_str = str(prev_value)
        curr_str = str(curr_value)

        # Simple approach: find common prefix and suffix, highlight the middle
        # Find common prefix
        i = 0
        while i < min(len(prev_str), len(curr_str)) and prev_str[i] == curr_str[i]:
            i += 1

        # Find common suffix
        j_prev = len(prev_str) - 1
        j_curr = len(curr_str) - 1
        while j_prev >= i and j_curr >= i and prev_str[j_prev] == curr_str[j_curr]:
            j_prev -= 1
            j_curr -= 1

        # Build highlighted string
        if i > 0 or j_curr < len(curr_str) - 1:
            prefix = curr_str[:i]
            changed = curr_str[i:j_curr + 1]
            suffix = curr_str[j_curr + 1:]

            # Highlight the changed part
            if changed:
                return f"{prefix}{colored(changed, 'yellow', attrs=['bold', 'underline'])}{suffix}"

        return curr_str

    def _output_results(self, result: Dict[str, Any], output_file: str = None, output_format: str = 'yaml'):
        """Output analysis results in specified format"""

        # Map HIML's yaml/json to our extended formats (text, dot, markdown)
        # HIML supports: yaml, json
        # We add: text (default for terminal), dot (graphviz), markdown (docs)

        if output_format == 'json':
            import json
            output = json.dumps(result, indent=2, default=str)
        elif output_format == 'yaml':
            import yaml
            output = yaml.dump(result, default_flow_style=False, sort_keys=False)
        elif output_format == 'dot':
            output = self._format_as_dot(result)
        elif output_format == 'markdown':
            output = self._format_as_markdown(result)
        else:  # Default to text for human-readable output
            output = self._format_as_text(result)

        # Write to file or stdout
        if output_file:
            os.makedirs(os.path.dirname(output_file), exist_ok=True) if os.path.dirname(output_file) else None
            with open(output_file, 'w') as f:
                f.write(output)
            logger.info(f"Results written to: {output_file}")
        else:
            print(output)

    def _format_as_text(self, result: Dict[str, Any]) -> str:
        """Format results as human-readable text"""
        output = []

        # Check if this is analyze output (has 'summary' key)
        if 'summary' in result and 'layers' in result:
            # analyze command
            output.append(colored("=" * 80, 'cyan'))
            output.append(colored("HIERARCHICAL CONFIGURATION ANALYSIS", 'cyan', attrs=['bold']))
            output.append(colored("=" * 80, 'cyan'))
            output.append(
                f"Config Path: {colored(result['summary'].get('config_path', 'N/A'), 'white', attrs=['bold'])}")
            output.append(f"Total Layers: {colored(str(result['summary'].get('total_layers', 0)), 'cyan')}")
            output.append("")

            for layer in result['layers']:
                # Layer path in white
                output.append(f"Layer: {colored(layer['path'], 'white', attrs=['bold'])}")

                # New variables in green
                new_count = len(layer['new_vars'])
                output.append(f"  New Variables: {colored(str(new_count), 'green', attrs=['bold'])}")
                if layer['new_vars']:
                    for var in layer['new_vars'][:10]:  # Show first 10
                        output.append(f"    {colored('+', 'green', attrs=['bold'])} {colored(var, 'green')}")
                    if len(layer['new_vars']) > 10:
                        output.append(
                            colored(f"    ... and {len(layer['new_vars']) - 10} more", 'green', attrs=['dark']))

                # Overridden variables in yellow
                override_count = len(layer['overridden_vars'])
                output.append(f"  Overridden Variables: {colored(str(override_count), 'yellow', attrs=['bold'])}")
                if layer['overridden_vars']:
                    for var in layer['overridden_vars'][:10]:
                        output.append(f"    {colored('~', 'yellow', attrs=['bold'])} {colored(var, 'yellow')}")
                    if len(layer['overridden_vars']) > 10:
                        output.append(
                            colored(f"    ... and {len(layer['overridden_vars']) - 10} more", 'yellow', attrs=['dark']))

                # Unchanged in dim white
                output.append(f"  Unchanged: {colored(str(layer['unchanged_vars']), 'white', attrs=['dark'])}")
                output.append("")

        # Check if this is visualize output (has 'root' key)
        elif 'root' in result and 'layers' in result:
            # visualize command
            output.append(colored("=" * 80, 'cyan'))
            output.append(colored("CONFIGURATION HIERARCHY VISUALIZATION", 'cyan', attrs=['bold']))
            output.append(colored("=" * 80, 'cyan'))
            output.append(f"Root Path: {colored(result['root'], 'white', attrs=['bold'])}")
            output.append(f"Total Layers: {colored(str(len(result['layers'])), 'cyan')}")
            output.append("")

            # Show layer contribution summary (what each folder adds)
            if result.get('layer_contributions'):
                output.append(colored("Variable Contributions by Layer:", 'cyan', attrs=['bold']))
                total_vars = result['layers'][-1]['var_count'] if result['layers'] else 0
                output.append(f"Total Variables: {colored(str(total_vars), 'yellow', attrs=['bold'])}")
                output.append("")

                # Sort by delta (highest contributors first)
                sorted_contributions = sorted(result['layer_contributions'], key=lambda x: x['delta'], reverse=True)

                for contrib in sorted_contributions:
                    delta_str = colored(f"+{contrib['delta']}", 'green', attrs=['bold'])
                    output.append(f"  {delta_str:20} {colored(contrib['path'], 'white')}")

                    # Show files in this layer with actual contributions
                    if contrib['files'] and 'file_contributions' in contrib:
                        file_contribs = contrib['file_contributions']

                        # Sort files by total contribution (new + overridden + interpolated)
                        def get_total(item):
                            stats = item[1]
                            if isinstance(stats, dict):
                                return stats.get('new', 0) + stats.get('overridden', 0) + stats.get('interpolated', 0)
                            return stats

                        sorted_files = sorted(file_contribs.items(), key=get_total, reverse=True)

                        for file, stats in sorted_files:
                            if isinstance(stats, dict):
                                parts = []
                                if stats['new'] > 0:
                                    parts.append(colored(f"+{stats['new']} new", 'green', attrs=['dark']))
                                if stats['interpolated'] > 0:
                                    parts.append(colored(f"~{stats['interpolated']} interp", 'blue', attrs=['dark']))
                                if stats['overridden'] > 0:
                                    parts.append(colored(f"!{stats['overridden']} override", 'yellow', attrs=['dark']))

                                if parts:
                                    stats_str = f" ({', '.join(parts)})"
                                    output.append(
                                        f"                       {colored('•', 'cyan')} {colored(file, 'cyan', attrs=['dark'])}{stats_str}")
                                else:
                                    output.append(
                                        f"                       {colored('•', 'cyan')} {colored(file, 'cyan', attrs=['dark'])}")
                            else:
                                # Old format (just a number)
                                if stats > 0:
                                    output.append(
                                        f"                       {colored('•', 'cyan')} {colored(file, 'cyan', attrs=['dark'])} {colored(f'(+{stats} keys)', 'green', attrs=['dark'])}")
                                else:
                                    output.append(
                                        f"                       {colored('•', 'cyan')} {colored(file, 'cyan', attrs=['dark'])}")
                    output.append("")

                output.append(colored("─" * 80, 'cyan', attrs=['dark']))
                output.append("")

            # Create tree structure
            prev_depth = -1
            prev_var_count = 0
            for i, layer in enumerate(result['layers']):
                indent = "  " * layer['depth']
                branch = "└─" if i == len(result['layers']) - 1 else "├─"

                # Color branch based on depth change
                depth_increased = layer['depth'] > prev_depth
                branch_color = 'green' if depth_increased else 'white'

                # Color path and show variable count
                path_str = f"{indent}{colored(branch, branch_color)} {colored(layer['path'], 'white', attrs=['bold'])}"
                output.append(path_str)

                # Color variable count based on size
                var_count = layer['var_count']
                if var_count < 100:
                    count_color = 'white'
                elif var_count < 200:
                    count_color = 'cyan'
                else:
                    count_color = 'yellow'

                # Calculate delta from previous layer
                delta = var_count - prev_var_count
                delta_str = ""
                if i > 0:  # Don't show delta for first layer
                    if delta > 0:
                        delta_str = f" {colored(f'(+{delta})', 'green', attrs=['bold'])}"
                    elif delta == 0:
                        delta_str = f" {colored('(no change)', 'white', attrs=['dark'])}"
                    else:
                        delta_str = f" {colored(f'({delta})', 'red', attrs=['bold'])}"

                output.append(
                    f"{indent}   Variables: {colored(str(var_count), count_color, attrs=['bold'])}{delta_str}")

                # Show all files at this layer (no trimming) with contributions
                if 'files' in layer and layer['files']:
                    file_contribs = layer.get('file_contributions', {})

                    # Calculate total from files
                    total_from_files = 0
                    for file in layer['files']:
                        stats = file_contribs.get(file, {})
                        if isinstance(stats, dict):
                            total_from_files += stats.get('new', 0) + stats.get('interpolated', 0) + stats.get(
                                'overridden', 0)
                        else:
                            total_from_files += stats

                    # Show each file
                    for file in layer['files']:
                        stats = file_contribs.get(file, {})
                        if isinstance(stats, dict):
                            parts = []
                            if stats.get('new', 0) > 0:
                                parts.append(colored(f"+{stats['new']}", 'green', attrs=['dark']))
                            if stats.get('interpolated', 0) > 0:
                                parts.append(colored(f"~{stats['interpolated']}", 'blue', attrs=['dark']))
                            if stats.get('overridden', 0) > 0:
                                parts.append(colored(f"!{stats['overridden']}", 'yellow', attrs=['dark']))

                            if parts:
                                stats_str = f" ({', '.join(parts)})"
                                output.append(
                                    f"{indent}     {colored('•', 'cyan')} {colored(file, 'cyan', attrs=['dark'])}{stats_str}")
                            else:
                                output.append(
                                    f"{indent}     {colored('•', 'cyan')} {colored(file, 'cyan', attrs=['dark'])}")
                        else:
                            # Old format fallback
                            if stats > 0:
                                output.append(
                                    f"{indent}     {colored('•', 'cyan')} {colored(file, 'cyan', attrs=['dark'])} {colored(f'(+{stats})', 'green', attrs=['dark'])}")
                            else:
                                output.append(
                                    f"{indent}     {colored('•', 'cyan')} {colored(file, 'cyan', attrs=['dark'])}")

                    # Show unaccounted keys (from HIML merge/interpolation)
                    if delta > 0 and total_from_files < delta:
                        unaccounted = delta - total_from_files

                        # Find the immediate parent layer
                        parent_layer = None
                        layer_paths = [l['path'] for l in result['layers']]
                        current_index = layer_paths.index(layer['path'])
                        if current_index > 0:
                            parent_layer = layer_paths[current_index - 1]

                        if parent_layer:
                            output.append(
                                f"{indent}     {colored('•', 'magenta')} {colored('(interpolation inheritance)', 'magenta', attrs=['dark'])} {colored(f'(+{unaccounted})', 'magenta', attrs=['dark'])} {colored(f'← from {parent_layer}', 'white', attrs=['dark'])}")
                        else:
                            output.append(
                                f"{indent}     {colored('•', 'magenta')} {colored('(interpolation inheritance)', 'magenta', attrs=['dark'])} {colored(f'(+{unaccounted})', 'magenta', attrs=['dark'])}")

                output.append("")

                prev_depth = layer['depth']
                prev_var_count = var_count

            output.append(colored("─" * 80, 'cyan', attrs=['dark']))
            output.append("")
            output.append(colored("Legend:", 'cyan', attrs=['bold']))
            output.append(f"  {colored('+N', 'green', attrs=['bold'])}    New keys (first appearance)")
            output.append(
                f"  {colored('~N', 'blue', attrs=['bold'])}    Interpolation resolved (fewer {{{{}}}} tokens)")
            output.append(f"  {colored('!N', 'yellow', attrs=['bold'])}    Override (value changed)")
            output.append(
                f"  {colored('(interpolation inheritance)', 'magenta', attrs=['dark'])} Keys inherited through HIML merge from parent layers")
            output.append("")
            output.append(
                colored("Tip: Use --output-format dot to generate a GraphViz diagram", 'cyan', attrs=['dark']))

        elif 'trace' in result:
            # trace command
            output.append(colored("=" * 80, 'cyan'))
            output.append(colored(f"VALUE TRACE: {result['key']}", 'cyan', attrs=['bold']))
            if result.get('is_dict'):
                output.append(colored("(Dictionary/Object)", 'cyan'))
            output.append(colored("=" * 80, 'cyan'))
            output.append(f"Config Path: {colored(result['config_path'], 'white', attrs=['bold'])}")
            output.append("")

            # Show suggestions if key not found
            if 'note' in result:
                output.append(colored(f"⚠️  {result['note']}", 'yellow'))
                output.append("")
                if 'suggestions' in result:
                    output.append(colored("Suggested keys (use full dotted path):", 'yellow'))
                    for suggestion in result['suggestions']:
                        output.append(f"  • {colored(suggestion, 'cyan')}")
                    output.append("")
                    output.append("Example:")
                    output.append(f"  kompos ... explore trace --key {colored(result['suggestions'][0], 'cyan')}")
                    output.append("")

            for step in result['trace']:
                # Color-coded status symbols
                status_colors = {
                    'new': ('green', '[NEW]'),
                    'interpolated': ('blue', '[INTERP]'),
                    'overridden': ('yellow', '[OVERRIDE]'),
                    'changed': ('magenta', '[CHANGED]'),
                    'unchanged': ('white', ''),
                    'undefined': ('red', '[UNDEFINED]')
                }
                status_color, status_symbol = status_colors.get(step['status'], ('white', ''))

                # Layer path in dim white
                output.append(f"  {colored(step['layer'], 'white', attrs=['dark'])}")

                # Value with highlighted changes and colored status
                curr_value = str(step['value'])

                # Highlight changes if there's a previous value
                if step.get('prev_value') is not None and step['status'] in ['interpolated', 'overridden']:
                    curr_value = self._highlight_diff(step['prev_value'], curr_value)

                value_str = f"    Value: {curr_value}"
                if status_symbol:
                    value_str += f" {colored(status_symbol, status_color, attrs=['bold'])}"
                output.append(value_str)

                # If it's a dictionary, show the keys
                if 'dict_keys' in step:
                    output.append(f"    Keys: {colored(', '.join(sorted(step['dict_keys'])), 'cyan')}")

                output.append("")

        elif 'matrix' in result:
            # compare command
            output.append("=" * 80)
            output.append("CONFIGURATION COMPARISON MATRIX")
            output.append("=" * 80)
            output.append("")

            # Build table
            for key, values in result['matrix'].items():
                output.append(f"Key: {key}")
                for path, value in values.items():
                    output.append(f"  {path}: {value}")
                output.append("")

        elif 'unresolved' in result:
            # analyze-interpolation command
            output.append(colored("=" * 80, 'red'))
            output.append(colored("UNRESOLVED INTERPOLATION ANALYSIS", 'red', attrs=['bold']))
            output.append(colored("=" * 80, 'red'))
            output.append(f"Config Path: {colored(result['config_path'], 'white', attrs=['bold'])}")
            output.append("")

            if result.get('excluded_keys'):
                output.append(f"Excluded Keys: {colored(', '.join(result['excluded_keys']), 'yellow')}")
                output.append("")

            for item in result['unresolved']:
                output.append(colored(f"Interpolation: {item['interpolation']}", 'red', attrs=['bold']))
                if item['key_path']:
                    output.append(f"  Key Path: {colored(item['key_path'], 'cyan')}")
                output.append("")

                # Show value trace if available
                if item.get('trace') and item['trace'].get('trace'):
                    output.append(colored("  Value Trace (hierarchy evolution):", 'blue', attrs=['bold']))
                    for step in item['trace']['trace'][:5]:  # Show top 5 layers
                        layer_short = step['layer'].replace('configs/', '')
                        value_str = str(step['value']) if step['value'] is not None else 'undefined'
                        status = step['status'].upper()

                        # Color code by status
                        status_colors = {
                            'NEW': 'green',
                            'OVERRIDDEN': 'yellow',
                            'INTERPOLATED': 'blue',
                            'UNCHANGED': 'white',
                            'UNDEFINED': 'red'
                        }
                        status_color = status_colors.get(status, 'white')

                        output.append(f"    {layer_short}")
                        output.append(
                            f"      Value: {colored(value_str, 'white')} {colored('[' + status + ']', status_color)}")

                    if len(item['trace']['trace']) > 5:
                        output.append(f"      ... and {len(item['trace']['trace']) - 5} more layers")
                    output.append("")

                # Show sources
                if item['sources']:
                    output.append(colored("  Found in:", 'yellow'))
                    for source in item['sources']:
                        rel_path = source['file']
                        output.append(f"    {colored(rel_path, 'white')}:{colored(str(source['line']), 'cyan')}")
                        output.append(f"      {colored(source['content'], 'white', attrs=['dark'])}")
                    output.append("")
                else:
                    output.append(colored("  Source not found in config hierarchy", 'red'))
                    output.append("")

                # Show diagnosis
                if item['causes']:
                    output.append(colored("  Possible Causes:", 'yellow', attrs=['bold']))
                    for cause in item['causes']:
                        output.append(f"    • {colored(cause, 'yellow')}")
                    output.append("")

            output.append(colored("Suggestions:", 'green', attrs=['bold']))
            output.append("  1. Check if key should be excluded from config generation")
            output.append("  2. Verify config hierarchy has required layers (region, cluster, etc.)")
            output.append("  3. Move composition-specific config to appropriate defaults file")
            output.append("  4. Add missing layer to config path if needed")
            output.append("")

        else:
            # Generic output
            output.append(str(result))

        return "\n".join(output)

    def _format_as_dot(self, result: Dict[str, Any]) -> str:
        """Format results as GraphViz DOT diagram with rich visualization"""
        lines = []
        lines.append('digraph hierarchy {')
        lines.append('  rankdir=TB;')
        lines.append('  bgcolor="white";')
        lines.append('  node [shape=box, style="rounded,filled", fontname="Arial", fontsize=12];')
        lines.append('  edge [fontname="Arial", fontsize=10];')
        lines.append('')

        # Add legend
        lines.append('  // Legend')
        lines.append('  subgraph cluster_legend {')
        lines.append('    label="Legend";')
        lines.append('    style=filled;')
        lines.append('    color=lightgrey;')
        lines.append('    node [shape=plaintext];')
        lines.append('    legend [label=<')
        lines.append('      <table border="0" cellborder="0" cellspacing="0">')
        lines.append('        <tr><td align="left"><b>Node Colors:</b></td></tr>')
        lines.append('        <tr><td align="left">🟢 Green: Small (&lt;100 vars)</td></tr>')
        lines.append('        <tr><td align="left">🔵 Cyan: Medium (100-199 vars)</td></tr>')
        lines.append('        <tr><td align="left">🟡 Yellow: Large (200+ vars)</td></tr>')
        lines.append('        <tr><td><br/></td></tr>')
        lines.append('        <tr><td align="left"><b>Edge Labels:</b></td></tr>')
        lines.append('        <tr><td align="left">+N = Variables added</td></tr>')
        lines.append('      </table>')
        lines.append('    >];')
        lines.append('  }')
        lines.append('')

        if 'layers' in result:
            prev_var_count = 0
            for i, layer in enumerate(result['layers']):
                node_id = f"layer{i}"

                # Determine node color based on variable count
                var_count = layer.get('var_count', 0)
                if var_count < 100:
                    fillcolor = 'lightgreen'
                elif var_count < 200:
                    fillcolor = 'lightblue'
                else:
                    fillcolor = 'lightyellow'

                # Build node label with HTML-like formatting
                path = layer['path'].replace('/', '/\n')  # Break long paths
                label_lines = [f'<b>{path}</b>']
                label_lines.append(f'<br/><font point-size="10">Total: {var_count} vars</font>')

                # Show delta
                delta = var_count - prev_var_count
                if i > 0 and delta > 0:
                    label_lines.append(f'<font point-size="10" color="darkgreen">(+{delta})</font>')

                # Show files if available
                if 'files' in layer and layer['files']:
                    label_lines.append('<br/>')
                    file_contribs = layer.get('file_contributions', {})
                    for file in layer['files'][:3]:  # Show max 3 files
                        stats = file_contribs.get(file, {})
                        if isinstance(stats, dict):
                            total = stats.get('new', 0) + stats.get('interpolated', 0) + stats.get('overridden', 0)
                            if total > 0:
                                label_lines.append(f'<font point-size="9">• {file} (+{total})</font>')
                            else:
                                label_lines.append(f'<font point-size="9">• {file}</font>')
                        else:
                            if stats > 0:
                                label_lines.append(f'<font point-size="9">• {file} (+{stats})</font>')

                    if len(layer['files']) > 3:
                        label_lines.append(f'<font point-size="9">... +{len(layer["files"]) - 3} more</font>')

                label = '<' + '<br/>'.join(label_lines) + '>'
                lines.append(f'  {node_id} [label={label}, fillcolor="{fillcolor}"];')

                # Add edge from previous layer with delta label
                if i > 0:
                    edge_label = f'+{delta}' if delta > 0 else 'inherited'
                    lines.append(
                        f'  layer{i - 1} -> {node_id} [label="{edge_label}", color="darkgreen", fontcolor="darkgreen"];')

                prev_var_count = var_count

        lines.append('}')
        return '\n'.join(lines)

    def _format_as_markdown(self, result: Dict[str, Any]) -> str:
        """Format results as Markdown"""
        output = []

        output.append("# Configuration Analysis")
        output.append("")

        if 'layers' in result and isinstance(result['layers'], list):
            output.append("## Hierarchy Layers")
            output.append("")
            for layer in result['layers']:
                output.append(f"### {layer['path']}")
                output.append("")
                output.append(f"- **New Variables**: {len(layer['new_vars'])}")
                output.append(f"- **Overridden Variables**: {len(layer['overridden_vars'])}")
                output.append(f"- **Total Variables**: {layer['total_vars']}")
                output.append("")

        return "\n".join(output)

    @staticmethod
    def execution(args, extra_args, default_output_path, composition, raw_config):
        """No actual execution needed - analysis is done in execution_configuration"""
        cmd = ""
        return dict(command=cmd)
