# Copyright 2026 Adobe. All rights reserved.
# This file is licensed to you under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License. You may obtain a copy
# of the License at http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software distributed under
# the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR REPRESENTATIONS
# OF ANY KIND, either express or implied. See the License for the specific language
# governing permissions and limitations under the License.

import json
import logging
import os
import sys
import time

import yaml
from deepmerge import Merger

from kompos.parser import SubParserConfig
from kompos.runner import GenericRunner
from kompos.helpers import console

logger = logging.getLogger(__name__)

RUNNER_TYPE = "helm"

# Key injected into context during interpolation, stripped from output.
# Isolates chart values from kompos context keys — never appears in output files.
DEFAULT_ENCLOSING_KEY = "__helm_values__"

# Deepmerge strategy: dicts merge, lists append, conflicts override
_MERGER = Merger(
    [(dict, ["merge"]), (list, ["append"])],
    ["override"],
    ["override"]
)


class HelmParserConfig(SubParserConfig):
    def get_name(self):
        return RUNNER_TYPE

    def get_help(self):
        return 'Render himl-templated Helm values for a cluster'

    def configure(self, parser):
        parser.add_argument('subcommand',
                            metavar='SUBCOMMAND',
                            choices=['generate', 'list'],
                            help='Action to perform: generate | list')

        # generate options
        parser.add_argument('--charts-dir',
                            metavar='PATH',
                            help='Root dir of chart subdirs; defaults to helm.config.charts_dir in .komposconfig.yaml')
        parser.add_argument('--chart-dir',
                            metavar='PATH',
                            help='Single chart directory for local dev (chart name inferred from dir name)')
        parser.add_argument('--dry-run',
                            action='store_true',
                            help='Print rendered output to stdout, do not write files')

        # list options
        parser.add_argument('--output-format',
                            dest='list_format',
                            choices=['table', 'yaml', 'json'],
                            default='table',
                            help='Output format for list (default: table)')

        self.add_himl_arguments(parser)
        return parser

    def get_epilog(self):
        return '''
Examples:
  # Render all enabled charts (charts_dir from .komposconfig.yaml)
  kompos configs/cloud=aws/.../cluster=cheeta/composition=helm-values helm generate

  # Override charts directory
  kompos configs/.../composition=helm-values \\
      helm generate --charts-dir /path/to/k8s-apps-deploy/applications/laser

  # Single chart (local dev)
  kompos configs/.../composition=helm-values \\
      helm generate --chart-dir /path/to/applications/laser/contour-ingress-controller

  # Dry-run (template under development)
  kompos configs/.../composition=helm-values \\
      helm generate --dry-run --skip-interpolation-validation

  # List enabled charts
  kompos configs/.../composition=helm-values helm list
        '''


class HelmRunner(GenericRunner):
    """
    Renders himl-templated Helm values for a cluster.

    Context assembly:
      1. raw_config  — full kompos hierarchy (cluster, env, region, account, ...)
      2. tfe_outputs — runtime infra state (global.infra.* from tfe-outputs.yaml)

    Values generation (per enabled chart):
      context[enclosing_key] = values_dict     # inject under internal key
      resolve_interpolations(context)           # resolve {{}} in-place
      rendered = context.pop(enclosing_key)     # extract clean values

    Output:
      generated/clusters/{cluster}/argoapps/{app}.yaml
    """


    def __init__(self, kompos_config, config_path, execute):
        super(HelmRunner, self).__init__(kompos_config, config_path, execute, RUNNER_TYPE)

        helm_config = self.kompos_config.get_runtime_setting(
            self.runner_type, 'config', {})

        self.enclosing_key      = helm_config.get('enclosing_key',    DEFAULT_ENCLOSING_KEY)
        self.tfe_outputs_path   = helm_config.get('tfe_outputs_path', 'outputs/tfe-outputs.yaml')
        self.argoapps_subdir    = helm_config.get('output_subdir',    'argoapps')
        self.base_output_dir    = helm_config.get('base_output_dir',  './generated')
        self.default_charts_dir = helm_config.get('charts_dir',       None)

    def run_configuration(self, args):
        self.validate_runner = False
        self.ordered_compositions = False
        self.reverse = False
        self.generate_output = False

    def execution_configuration(self, composition, config_path, default_output_path,
                                raw_config, filtered_keys, excluded_keys):
        args = self.himl_args

        if args.subcommand == 'list':
            self.run_list(raw_config, getattr(args, 'list_format', 'table'))
            return

        if args.subcommand == 'generate':
            charts_dir = args.charts_dir or self.default_charts_dir
            if not charts_dir and not args.chart_dir:
                console.print_error(
                    "Missing charts directory for 'generate'.",
                    "Provide --charts-dir PATH, --chart-dir PATH, "
                    "or set helm.config.charts_dir in .komposconfig.yaml"
                )
                sys.exit(1)
            self.run_generate(args, raw_config, charts_dir)
            return

    @staticmethod
    def execution(args, extra_args, default_output_path, composition, raw_config):
        return dict(command="")

    # ── list ──────────────────────────────────────────────────────────────────

    def run_list(self, raw_config, fmt):
        cluster_name = self.get_composition_name(raw_config)
        charts = self.enabled_charts(raw_config)

        print(f"\nEnabled charts for cluster: {cluster_name}\n")

        if fmt == 'yaml':
            print(yaml.dump({'helm': {'charts': {k: v for k, v in charts.items()}}},
                            default_flow_style=False))
            return

        if fmt == 'json':
            print(json.dumps({'helm': {'charts': {k: v for k, v in charts.items()}}}, indent=2))
            return

        if not charts:
            print("  (no charts enabled)")
            return

        print(f"  {'CHART':<45} {'VERSION':<12} STATUS")
        print(f"  {'─'*45} {'─'*12} ──────")
        for name, cfg in sorted(charts.items()):
            version = cfg.get('version', '(unset)')
            print(f"  {name:<45} {version:<12} enabled")
        print()

    # ── generate ──────────────────────────────────────────────────────────────

    def run_generate(self, args, raw_config, charts_dir):
        start = time.time()
        cluster_name = self.get_composition_name(raw_config)

        if not cluster_name:
            console.print_error(
                "Could not determine cluster name.",
                "Ensure composition.instance is set in composition=helm-values config."
            )
            sys.exit(1)

        console.print_section_header(f"Helm Values Render: {cluster_name}")

        context = self.build_context(raw_config, cluster_name)

        # --chart-dir: single chart mode — path comes directly from the arg
        if args.chart_dir:
            chart_dir_abs = os.path.abspath(args.chart_dir)
            app_name      = os.path.basename(chart_dir_abs)
            chart_files   = {app_name: os.path.join(chart_dir_abs, 'values.yaml')}
            disabled, untracked = set(), set()

        # --charts-dir / komposconfig default: scan filesystem, filter to enabled
        else:
            charts_dir    = os.path.abspath(charts_dir)
            charts_on_fs  = self.find_charts(charts_dir)
            enabled, disabled, untracked = self.categorize_charts(charts_on_fs, raw_config)

            if not enabled:
                console.print_warning("No enabled charts found in helm.charts.*")
                return

            chart_files = {
                app_name: os.path.join(charts_dir, app_name, 'values.yaml')
                for app_name in enabled
            }

        argoapps_dir = os.path.join(
            self.base_output_dir, 'clusters', cluster_name, self.argoapps_subdir)

        dry_run = getattr(args, 'dry_run', False)
        rendered_count = 0

        for app_name, values_path in sorted(chart_files.items()):
            rendered = self.render_values(app_name, values_path, context)
            if rendered is None:
                continue

            if dry_run:
                print(f"\n# ── {app_name} ──────────────────────────────────────")
                print(yaml.dump(rendered, default_flow_style=False))
            else:
                output_file = os.path.join(argoapps_dir, f"{app_name}.yaml")
                self.ensure_directory(output_file, is_file_path=True)
                with open(output_file, 'w') as f:
                    yaml.dump(rendered, f, default_flow_style=False, sort_keys=False)
                console.print_success(f"Rendered {app_name}")
                console.print_file_generation("argoapps", output_file)

            rendered_count += 1

        if not dry_run:
            self.prune_argoapps(argoapps_dir, rendered=set(chart_files.keys()))

        self.report_chart_status(disabled, untracked)
        console.print_summary(total_files=rendered_count, elapsed_time=time.time() - start)

    # ── context ───────────────────────────────────────────────────────────────

    def build_context(self, raw_config, cluster_name):
        """
        Merge kompos hierarchy + TFE outputs into the interpolation context.

        raw_config  → top-level keys from the kompos tree walk
        tfe_outputs → global.infra.* overlaid on top
        """
        context = dict(raw_config)

        tfe_path = os.path.join(
            self.base_output_dir, 'clusters', cluster_name, self.tfe_outputs_path)

        if not os.path.exists(tfe_path):
            console.print_error(
                f"TFE outputs not found: {tfe_path}",
                "Ensure terraform has been applied and outputs exported before rendering helm values."
            )
            sys.exit(1)

        with open(tfe_path) as f:
            tfe_outputs = yaml.safe_load(f) or {}
        context = _MERGER.merge(context, tfe_outputs)
        logger.info(f"Loaded TFE outputs: {tfe_path}")

        context.pop(self.enclosing_key, None)
        return context

    # ── chart discovery ───────────────────────────────────────────────────────

    def find_charts(self, charts_dir):
        """Scan filesystem: return names of all chart dirs in charts_dir that contain values.yaml."""
        if not charts_dir or not os.path.isdir(charts_dir):
            return set()
        return {
            d for d in os.listdir(charts_dir)
            if os.path.isfile(os.path.join(charts_dir, d, 'values.yaml'))
        }

    def charts_config(self, raw_config):
        """Return the raw helm.charts.* dict from the kompos hierarchy."""
        return raw_config.get('helm', {}).get('charts', {})

    def categorize_charts(self, charts_on_fs, raw_config):
        """
        Compare filesystem state with hierarchy config.

        Returns three disjoint sets:
          enabled   — in helm.charts.* with enabled: true AND present on disk
          disabled  — in helm.charts.* with enabled: false AND present on disk
          untracked — present on disk but not in helm.charts.* at all
        """
        all_charts = self.charts_config(raw_config)
        configured = set(all_charts.keys())

        enabled   = {name for name, cfg in all_charts.items()
                     if isinstance(cfg, dict) and cfg.get('enabled', True)
                     and name in charts_on_fs}
        disabled  = {name for name, cfg in all_charts.items()
                     if isinstance(cfg, dict) and not cfg.get('enabled', True)
                     and name in charts_on_fs}
        untracked = charts_on_fs - configured

        return enabled, disabled, untracked

    def enabled_charts(self, raw_config):
        """Return charts enabled in helm.charts.* (used by run_list)."""
        charts_data = self.charts_config(raw_config)
        return {
            name: cfg
            for name, cfg in (charts_data or {}).items()
            if isinstance(cfg, dict) and cfg.get('enabled', True)
        }

    # ── rendering ─────────────────────────────────────────────────────────────

    def render_values(self, app_name, values_path, context):
        """
        Render a single values.yaml template against the interpolation context.

        Inject values under enclosing_key → resolve {{}} → pop and return clean values.
        Context is modified in-place but restored (enclosing_key is always popped).
        """
        if not os.path.exists(values_path):
            console.print_warning(f"values.yaml not found for '{app_name}': {values_path}")
            return None

        with open(values_path) as f:
            template = yaml.safe_load(f)

        if template is None:
            console.print_warning(f"Empty values.yaml for '{app_name}': {values_path}")
            return None

        if not isinstance(template, dict):
            console.print_warning(
                f"values.yaml for '{app_name}' is not a YAML mapping — skipping "
                f"(got {type(template).__name__})"
            )
            return None

        context[self.enclosing_key] = template

        try:
            self.resolve_interpolations(context)
        except Exception as e:
            logger.error(f"Interpolation failed for '{app_name}': {e}")
            context.pop(self.enclosing_key, None)
            raise

        return context.pop(self.enclosing_key)

    # ── reporting ─────────────────────────────────────────────────────────────

    def prune_argoapps(self, argoapps_dir, rendered):
        """
        Remove argoapps/ files for charts no longer rendered.

        argoapps/ is fully owned by helm generate — any .yaml not in the
        current rendered set is stale (disabled or removed from helm.charts.*).
        Pruning ensures ArgoCD never applies values from a disabled chart.
        """
        if not os.path.isdir(argoapps_dir):
            return
        for filename in os.listdir(argoapps_dir):
            if not filename.endswith('.yaml'):
                continue
            chart_name = filename[:-5]   # strip .yaml
            if chart_name not in rendered:
                stale_path = os.path.join(argoapps_dir, filename)
                os.remove(stale_path)
                console.print_warning(f"Pruned stale argoapps file: {stale_path}")

    def report_chart_status(self, disabled, untracked):
        """Report disabled and untracked charts after categorize_charts comparison."""
        disabled  = sorted(disabled)
        untracked = sorted(untracked)

        if disabled:
            print(f"\n  Disabled:")
            for name in disabled:
                print(f"    {name}")

        if untracked:
            print(f"\n  Untracked:")
            for name in untracked:
                print(f"    {name}")

        if disabled or untracked:
            print()
