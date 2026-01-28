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

from himl import ConfigRunner
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
        # Explore subcommand
        parser.add_argument('subcommand',
                            choices=['analyze', 'trace', 'visualize', 'compare'],
                            help='Exploration mode: analyze=distribution, trace=provenance, visualize=diagram, compare=matrix')

        # Trace-specific options
        parser.add_argument('--key',
                            type=str,
                            help='Specific config key to trace (for trace command)')

        # Compare-specific options
        parser.add_argument('--keys',
                            type=str,
                            nargs='+',
                            help='Specific keys to compare (for compare command)')

        # Add all HIML arguments (filter, exclude, skip-secrets, output-file, format, etc.)
        # These are needed for generate_config() calls and output handling
        ConfigRunner().get_parser(parser)

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
        else:
            logger.error("Unknown subcommand: %s", args.subcommand)
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
        logger.info("Analyzing configuration distribution from: %s", config_path)

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
                    skip_secrets=True
                )
            except Exception as e:
                logger.warning("Failed to generate config for %s: %s", layer_path, e)
                continue

            # Analyze changes from previous layer
            new_vars = []
            overridden_vars = []
            unchanged_vars = []

            for key, value in self._flatten_dict(layer_config).items():
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
            previous_config = self._flatten_dict(layer_config)

        return distribution

    def trace_value(self, config_path: str, key: str) -> Dict[str, Any]:
        """
        Trace a specific variable through the hierarchy.
        Shows where it originates and how it's overridden.
        Supports both leaf values and dictionary keys.
        """
        logger.info("Tracing key '%s' from: %s", key, config_path)

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
                    skip_secrets=True
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
                flat_config = self._flatten_dict(layer_config)
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
                logger.warning("Failed to trace in %s: %s", layer_path, e)

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
        logger.info("Visualizing hierarchy from: %s", config_path)

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
                    skip_secrets=True
                )

                flat_config = self._flatten_dict(layer_config)

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
                            parent_config = self._flatten_dict(parent_config_obj)
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
                                    file_flat = self._flatten_dict(file_data)

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
                                    logger.debug("Failed to analyze file %s: %s", file_path, e)
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
                logger.warning("Failed to analyze %s: %s", layer_path, e)

        hierarchy['output_format'] = output_format
        return hierarchy

    def compare_configs(self, config_path: str, keys: List[str] = None) -> Dict[str, Any]:
        """
        Compare configurations across different paths.
        Shows value differences in a matrix format.
        """
        logger.info("Comparing configurations from: %s", config_path)

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
                configs[path] = self._flatten_dict(
                    self.generate_config(
                        config_path=path,
                        skip_interpolation_validation=True,
                        skip_secrets=True
                    )
                )
            except Exception as e:
                logger.warning("Failed to generate config for %s: %s", path, e)

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

    def _flatten_dict(self, d: Dict[str, Any], parent_key: str = '', sep: str = '.') -> Dict[str, Any]:
        """
        Flatten nested dictionary into dot-notation keys.
        Example: {'vpc': {'cidr': '10.0.0.0/16'}} -> {'vpc.cidr': '10.0.0.0/16'}
        """
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key, sep=sep).items())
            else:
                items.append((new_key, v))
        return dict(items)

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
            logger.info("Results written to: %s", output_file)
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
