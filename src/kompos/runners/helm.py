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

from himl.interpolation import InterpolationValidator

from kompos.parser import SubParserConfig
from kompos.runner import GenericRunner
from kompos.helpers import console

logger = logging.getLogger(__name__)

RUNNER_TYPE = "helm"

# Key injected into context during interpolation, stripped from output.
# Isolates chart values from kompos context keys — never appears in output files.
DEFAULT_ENCLOSING_KEY = "__helm_values__"


class HelmParserConfig(SubParserConfig):
    def get_name(self):
        return RUNNER_TYPE

    def get_help(self):
        return 'Render himl-templated Helm values for a cluster'

    def configure(self, parser):
        parser.add_argument('subcommand',
                            metavar='SUBCOMMAND',
                            choices=['generate', 'list', 'delete'],
                            help='Action to perform: generate | list | delete')

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

  # Delete generated artifacts for a cluster
  kompos configs/.../composition=helm-values helm delete
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
        self.overrides_merge    = helm_config.get('overrides_merge',   False)
        self.overrides_subdir   = helm_config.get('overrides_subdir',  'overrides')
        self.bridge_filename    = helm_config.get('bridge_filename',   'bridge.yaml')
        self.symlink_generated  = helm_config.get('symlink_generated', False)

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
            self.run_generate(args, raw_config, charts_dir, config_path)
            return

        if args.subcommand == 'delete':
            self.run_delete(raw_config)
            return

    @staticmethod
    def execution(args, extra_args, default_output_path, composition, raw_config):
        return dict(command="")

    # ── delete ────────────────────────────────────────────────────────────────

    def run_delete(self, raw_config):
        """Delete all generated helm values for a cluster."""
        import shutil

        cluster_name = self.get_composition_name(raw_config)
        if not cluster_name:
            console.print_error("Could not determine cluster name.")
            sys.exit(1)

        argoapps_dir, chart_symlinks = self._output_paths(cluster_name)

        console.print_section_header(f"Helm Delete: {cluster_name}")
        removed = 0

        if os.path.isdir(argoapps_dir):
            shutil.rmtree(argoapps_dir)
            print(f"  {console.Colors.YELLOW}✗{console.Colors.RESET} {argoapps_dir}/")
            removed += 1

        for symlink_path, gen_dir in chart_symlinks:
            if os.path.islink(symlink_path) or os.path.isfile(symlink_path):
                os.remove(symlink_path)
                print(f"  {console.Colors.YELLOW}✗{console.Colors.RESET} {symlink_path}")
                removed += 1
            if os.path.isdir(gen_dir):
                remaining = [f for f in os.listdir(gen_dir) if f != 'README.md']
                if not remaining:
                    readme = os.path.join(gen_dir, 'README.md')
                    if os.path.isfile(readme):
                        os.remove(readme)
                    os.rmdir(gen_dir)

        if removed:
            print(f"\n  {console.Colors.GREEN}✓{console.Colors.RESET} Deleted {removed} artifact(s) for {cluster_name}")
        else:
            print(f"\n  No artifacts found for {cluster_name}")

    # ── output paths ─────────────────────────────────────────────────────────

    def _output_paths(self, cluster_name):
        """
        Return the output paths that generate/delete operate on.

        Returns:
            argoapps_dir: generated/clusters/{cluster}/helm-values/
            chart_symlinks: list of (symlink_path, parent_generated_dir) tuples
        """
        argoapps_dir = os.path.join(
            self.base_output_dir, 'clusters', cluster_name, self.argoapps_subdir)

        chart_symlinks = []
        charts_dir = self.default_charts_dir
        if charts_dir and os.path.isdir(charts_dir):
            for chart_name in os.listdir(charts_dir):
                gen_dir = os.path.join(charts_dir, chart_name, 'generated')
                symlink_path = os.path.join(gen_dir, f"{cluster_name}.yaml")
                chart_symlinks.append((symlink_path, gen_dir))

        return argoapps_dir, chart_symlinks

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

    def run_generate(self, args, raw_config, charts_dir, config_path=None):
        start = time.time()
        cluster_name = self.get_composition_name(raw_config)

        if not cluster_name:
            console.print_error(
                "Could not determine cluster name.",
                "Ensure composition.instance is set in composition=helm-values config."
            )
            sys.exit(1)

        env_name = self.get_nested_value(raw_config, 'env.name')

        console.print_section_header(f"Helm Values Render: {cluster_name}")

        # Discover charts before loading TFE outputs — bail early if nothing enabled
        if args.chart_dir:
            chart_dir_abs = os.path.abspath(args.chart_dir)
            app_name      = os.path.basename(chart_dir_abs)
            chart_files   = {app_name: os.path.join(chart_dir_abs, self.bridge_filename)}
            disabled, untracked = set(), set()
        else:
            charts_dir    = os.path.abspath(charts_dir)
            charts_on_fs  = self.find_charts(charts_dir)
            enabled, disabled, untracked = self.categorize_charts(charts_on_fs, raw_config)

            if not enabled:
                console.print_warning("No enabled charts found in helm.charts.*")
                self.report_chart_status(disabled, untracked)
                return

            chart_files = {
                app_name: os.path.join(charts_dir, app_name, self.bridge_filename)
                for app_name in enabled
            }

        infra_outputs_path = os.path.join(
            self.base_output_dir, 'clusters', cluster_name, self.tfe_outputs_path)

        # Build context once — hierarchy + infra outputs, reused for all charts
        context = self._build_context(config_path, infra_outputs_path)

        argoapps_dir, _ = self._output_paths(cluster_name)

        dry_run = getattr(args, 'dry_run', False)
        rendered_count = 0
        validation_errors = []

        hierarchy_path = config_path or self.config_path
        print(f"\n  {console.Colors.BOLD}{console.Colors.WHITE}Context:{console.Colors.RESET}")
        print(f"    {console.Colors.DIM}Hierarchy:{console.Colors.RESET} {console.Colors.BLUE}{hierarchy_path}{console.Colors.RESET}")
        print(f"    {console.Colors.DIM}Infra:{console.Colors.RESET}     {console.Colors.CYAN}{infra_outputs_path}{console.Colors.RESET}")
        print(f"\n  {console.Colors.DIM}Output:{console.Colors.RESET} {console.Colors.WHITE}{argoapps_dir}/{console.Colors.RESET}")
        print(f"\n  {console.Colors.BOLD}{console.Colors.WHITE}Charts:{console.Colors.RESET}\n")

        for app_name, values_path in sorted(chart_files.items()):
            rendered = self.render_values(app_name, values_path, context,
                                          cluster_name, env_name)
            if rendered is None:
                continue

            # Track validation warnings regardless of dry-run
            validation_warning = getattr(self, '_last_validation_warning', None)
            if validation_warning:
                validation_errors.append(app_name)

            if dry_run:
                print(f"\n# ── {app_name} ──────────────────────────────────────")
                if validation_warning:
                    print(f"# ⚠ {validation_warning}")
                print(yaml.dump(rendered, default_flow_style=False))
                self._last_validation_warning = None
            else:
                # Source of truth: generated/clusters/{cluster}/helm-values/{chart}.yaml
                output_file = os.path.join(argoapps_dir, f"{app_name}.yaml")
                self.ensure_directory(output_file, is_file_path=True)
                with open(output_file, 'w') as f:
                    yaml.dump(rendered, f, default_flow_style=False, sort_keys=False)

                # Symlink: charts/{chart}/generated/{cluster}.yaml → source of truth
                if self.symlink_generated:
                    chart_dir = os.path.dirname(values_path)
                    per_chart_dir = os.path.join(chart_dir, 'generated')
                    per_chart_file = os.path.join(per_chart_dir, f"{cluster_name}.yaml")
                    self.ensure_directory(per_chart_file, is_file_path=True)
                    rel_target = os.path.relpath(output_file, per_chart_dir)
                    if os.path.islink(per_chart_file) or os.path.exists(per_chart_file):
                        os.remove(per_chart_file)
                    os.symlink(rel_target, per_chart_file)

                logger.debug(f"Wrote {output_file}")
                if self.symlink_generated:
                    logger.debug(f"Symlink {per_chart_file} -> {output_file}")
                has_bridge = os.path.isfile(values_path)
                overrides_info = getattr(self, '_last_loaded_overrides', [])
                tags = []
                if has_bridge:
                    tags.append(f'{console.Colors.CYAN}bridge{console.Colors.RESET}')
                if overrides_info:
                    tags.append(f'{console.Colors.MAGENTA}overrides{console.Colors.RESET}')
                tag_str = f" {console.Colors.DIM}[{console.Colors.RESET}{', '.join(tags)}{console.Colors.DIM}]{console.Colors.RESET}" if tags else ""
                print(f"    {console.Colors.GREEN}✓{console.Colors.RESET} {app_name:<40}{tag_str}")
                if validation_warning:
                    print(f"      {console.Colors.YELLOW}⚠ {validation_warning}{console.Colors.RESET}")
                for override_file in overrides_info:
                    print(f"      {console.Colors.DIM}+{console.Colors.RESET} {console.Colors.MAGENTA}{override_file}{console.Colors.RESET}")
                self._last_loaded_overrides = []
                self._last_validation_warning = None

            rendered_count += 1

        if not dry_run:
            self.prune_argoapps(argoapps_dir, rendered=set(chart_files.keys()))
            self._write_generated_readmes(argoapps_dir, cluster_name, env_name, chart_files)

        self.report_chart_status(disabled, untracked)
        console.print_summary(total_files=rendered_count, elapsed_time=time.time() - start)

        if validation_errors:
            console.print_error(
                f"Unresolved interpolations in {len(validation_errors)} chart(s): {', '.join(validation_errors)}")
            sys.exit(1)

    # ── context ───────────────────────────────────────────────────────────────

    def _build_context(self, config_path, infra_outputs_path):
        """
        Build interpolation context once — hierarchy walk + infra outputs merge.
        Reused for all charts to avoid repeated hierarchy walks.
        """
        raw_config = self.get_raw_config(config_path or self.config_path, None)
        context = dict(raw_config)

        infra_outputs = self.load_yaml_file(infra_outputs_path)
        if infra_outputs is None:
            console.print_error(
                f"Infra outputs not found: {infra_outputs_path}",
                "Ensure terraform has been applied and outputs exported before rendering helm values."
            )
            sys.exit(1)

        context = self.merge_configs(context, infra_outputs)
        context.pop(self.enclosing_key, None)
        return context

    # ── chart discovery ───────────────────────────────────────────────────────

    def find_charts(self, charts_dir):
        """
        Scan filesystem for chart dirs that have a bridge template or overrides.

        A chart dir qualifies if it contains bridge.yaml (bridge template)
        or an overrides/ subdirectory (operational values only).
        The chart registry (helm.charts.*) controls which are actually rendered —
        this is just filesystem discovery.
        """
        if not charts_dir or not os.path.isdir(charts_dir):
            return set()
        result = set()
        for d in os.listdir(charts_dir):
            chart_path = os.path.join(charts_dir, d)
            if not os.path.isdir(chart_path):
                continue
            has_bridge = os.path.isfile(os.path.join(chart_path, self.bridge_filename))
            has_overrides = os.path.isdir(os.path.join(chart_path, self.overrides_subdir))
            if has_bridge or has_overrides:
                result.add(d)
        return result

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

    def render_values(self, app_name, values_path, context,
                      cluster_name=None, env_name=None):
        """
        Render values for a chart against the cached context.

        Pipeline:
          1. Inject bridge template under enclosing key into context
          2. Resolve {{ }} interpolations (himl InterpolationResolver)
          3. Extract rendered values (pop enclosing key)
          4. Validate no {{ }} remain (himl InterpolationValidator)
          5. Merge overrides on top (default < env < cluster, wins)
        """
        chart_dir = os.path.dirname(values_path)
        has_bridge = os.path.isfile(values_path)

        # Step 1-4: bridge interpolation + validation
        bridge_values = None
        if has_bridge:
            template = self.load_yaml_file(values_path)
            if template:
                context[self.enclosing_key] = template
                try:
                    self.resolve_interpolations(context)
                except Exception as e:
                    logger.error(f"Interpolation failed for '{app_name}': {e}")
                    context.pop(self.enclosing_key, None)
                    raise
                bridge_values = context.pop(self.enclosing_key)
                try:
                    InterpolationValidator().check_all_interpolations_resolved(bridge_values)
                except Exception as e:
                    self._last_validation_warning = str(e)

        # Step 5: overrides merge
        loaded = []
        if self.overrides_merge:
            overrides_dir = os.path.join(chart_dir, self.overrides_subdir)
            for name in ['default.yaml', f'{env_name}.yaml', f'{cluster_name}.yaml']:
                path = os.path.join(overrides_dir, name)
                override = self.load_yaml_file(path)
                if override:
                    if bridge_values:
                        bridge_values = self.merge_configs(bridge_values, override)
                    else:
                        bridge_values = override
                    loaded.append(name)
        self._last_loaded_overrides = loaded

        return bridge_values

    # ── generated README ────────────────────────────────────────────────────

    def _write_generated_readmes(self, argoapps_dir, cluster_name, env_name, chart_files):
        """Write managed README.md in per-cluster and per-chart output directories."""
        charts_list = '\n'.join(f'  - `{name}.yaml`' for name in sorted(chart_files.keys()))

        template_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), 'data', 'templates', 'helm-readme.md')
        with open(template_path) as f:
            template = f.read()

        content = template.format(
            cluster_name=cluster_name,
            bridge_filename=self.bridge_filename,
            overrides_subdir=self.overrides_subdir,
            charts_list=charts_list,
        )

        # Per-cluster: generated/clusters/{cluster}/helm-values/README.md
        readme_path = os.path.join(argoapps_dir, 'README.md')
        self.ensure_directory(readme_path, is_file_path=True)
        with open(readme_path, 'w') as f:
            f.write(content)

        # Per-chart: charts/{chart}/generated/README.md (only when symlinks enabled)
        if self.symlink_generated:
            chart_template_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), 'data', 'templates', 'helm-chart-readme.md')
            with open(chart_template_path) as f:
                chart_template = f.read()

            for app_name, values_path in chart_files.items():
                chart_dir = os.path.dirname(values_path)
                per_chart_dir = os.path.join(chart_dir, 'generated')
                if os.path.isdir(per_chart_dir):
                    chart_content = chart_template.format(
                        chart_name=app_name,
                        bridge_filename=self.bridge_filename,
                        overrides_subdir=self.overrides_subdir,
                    )
                    per_chart_readme = os.path.join(per_chart_dir, 'README.md')
                    with open(per_chart_readme, 'w') as f:
                        f.write(chart_content)

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
            print(f"\n  {console.Colors.BOLD}{console.Colors.WHITE}Disabled:{console.Colors.RESET}\n")
            for name in disabled:
                print(f"    {console.Colors.DIM}–{console.Colors.RESET} {name}")

        if untracked:
            print(f"\n  {console.Colors.BOLD}{console.Colors.WHITE}Untracked:{console.Colors.RESET}\n")
            for name in untracked:
                print(f"    {console.Colors.DIM}?{console.Colors.RESET} {name}")

        if disabled or untracked:
            print()
