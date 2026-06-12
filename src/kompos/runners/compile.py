# Copyright 2026 Adobe. All rights reserved.
# This file is licensed to you under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License. You may obtain a copy
# of the License at http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software distributed under
# the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR REPRESENTATIONS
# OF ANY KIND, either express or implied. See the License for the specific language
# governing permissions and limitations under the License.

import argparse
import logging
import os
import shutil

from kompos.parser import SubParserConfig
from kompos.runner import GenericRunner, COMPOSITION_KEY, split_path
from kompos.helpers import console

logger = logging.getLogger(__name__)


def _get_runner_class(runner_type):
    """Lazy import runner class by type to avoid circular imports."""
    if runner_type == 'helm':
        from kompos.runners.helm import HelmRunner
        return HelmRunner
    if runner_type == 'tfe':
        from kompos.runners.tfe import TFERunner
        return TFERunner
    if runner_type == 'terraform':
        from kompos.runners.terraform import TerraformRunner
        return TerraformRunner
    if runner_type == 'manual':
        from kompos.runners.manual import ManualRunner
        return ManualRunner
    if runner_type == 'external':
        from kompos.runners.external import ExternalRunner
        return ExternalRunner
    return None


def _build_default_dispatch_args(runner_type):
    """
    Build a minimal args Namespace for dispatching to a runner.
    Returns None if the runner type doesn't support default dispatch.
    """
    if runner_type == 'helm':
        return argparse.Namespace(
            command='helm',
            subcommand='generate',
            charts_dir=None,
            chart_dir=None,
            dry_run=False,
            list_format='table',
            filter=None,
            exclude=None,
            himl_args=None,
        )
    if runner_type == 'tfe':
        return argparse.Namespace(
            command='tfe',
            subcommand='generate',
            workspace_only=False,
            tfvars_only=False,
            filter=None,
            exclude=None,
            himl_args=None,
        )
    if runner_type == 'manual':
        return argparse.Namespace(
            command='manual',
            subcommand='generate',
            dry_run=False,
            filter=None,
            exclude=None,
            himl_args=None,
        )
    if runner_type == 'external':
        return argparse.Namespace(
            command='external',
            subcommand='generate',
            dry_run=False,
            filter=None,
            exclude=None,
            himl_args=None,
        )
    if runner_type == 'terraform':
        # compile 'build' generates artifacts only (like tfe/helm); dry_run keeps
        # execution() a no-op so we never run terraform against live infra.
        return argparse.Namespace(
            command='terraform',
            subcommand='plan',
            dry_run=True,
            filter=None,
            exclude=None,
            himl_args=None,
        )
    return None

RUNNER_TYPE = "compile"

# Subcommands — the action to perform on each discovered composition
ACTIONS = ['build', 'destroy']


class CompileParserConfig(SubParserConfig):
    def get_name(self):
        return RUNNER_TYPE

    def get_help(self):
        return 'Graph-walk a config subtree and compile all compositions (build, destroy)'

    def configure(self, parser):
        parser.add_argument(
            'action',
            metavar='ACTION',
            choices=ACTIONS,
            nargs='?',
            default='build',
            help=f'Action to perform: {" | ".join(ACTIONS)} (default: build)'
        )
        parser.add_argument(
            '--prune',
            action='store_true',
            help='Remove generated artifacts for compositions no longer in configs/'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            help='Show what would be built/pruned without making changes'
        )
        self.add_himl_arguments(parser)
        return parser

    def get_epilog(self):
        return '''
Examples:
  # Build everything under a cluster (tfe + helm values, auto-detected)
  kompos configs/.../cluster=sloth compile build

  # Build everything under an entire region
  kompos configs/cloud=aws/project=aip-training/env=dev/region=or2 compile

  # Build everything + remove stale artifacts
  kompos configs/cloud=aws/project=aip-training compile build --prune

  # Show what would be built/pruned
  kompos configs/cloud=aws/project=aip-training compile build --dry-run --prune

  # (future) Destroy all compositions under a cluster
  kompos configs/.../cluster=sloth compile destroy

Routing is controlled by komposconfig.compositions.order.*:
  order:
    tfe:  [account, cell, cluster]
    helm: [helm-values]
'''


class CompileRunner(GenericRunner):
    """
    Meta-runner: graph-walks a config subtree, discovers ALL compositions at any depth,
    and routes each to its configured runner via komposconfig.compositions.order.*.

    Actions:
      build    — generate all artifacts (default)
      destroy  — (future) destroy all generated artifacts

    Options:
      --prune    remove stale generated artifacts for compositions no longer in configs/
      --dry-run  print what would be built/pruned without making changes
    """

    def __init__(self, kompos_config, config_path, execute):
        super(CompileRunner, self).__init__(kompos_config, config_path, execute, RUNNER_TYPE)

    def run_configuration(self, args):
        self.configure_passive()

    def run(self, args, extra_args):
        self.run_configuration(args)

        # Seed himl_args with defaults for dispatch
        _himl_parser = argparse.ArgumentParser()
        SubParserConfig.add_himl_arguments(None, _himl_parser)
        self.himl_args = _himl_parser.parse_args([])

        action  = getattr(args, 'action',  'build')
        dry_run = getattr(args, 'dry_run', False)
        prune   = getattr(args, 'prune',   False)

        routing   = self._build_routing_map()
        all_comps = self._walk_compositions(self.config_path)

        if not all_comps:
            console.print_warning("No compositions found under the given path.")
            return 0

        enabled_comps, disabled_comps = self._partition_enabled_compositions(all_comps)

        print(f"\n  Found {len(all_comps)} composition(s):\n")
        for comp_type, comp_path in enabled_comps:
            owner = routing.get(comp_type, '?')
            rel   = os.path.relpath(comp_path)
            suffix = '  (dry-run)' if dry_run else ''
            print(f"    [{owner}] {rel}{suffix}")
        for comp_type, comp_path in disabled_comps:
            owner = routing.get(comp_type, '?')
            rel   = os.path.relpath(comp_path)
            print(f"    [{owner}] {rel}  {console.Colors.DIM}(composition.enabled: false){console.Colors.RESET}")
        print()

        if action == 'build' and not dry_run:
            # Dispatch every composition (enabled AND disabled). Each runner decides
            # what a disabled composition still emits via generate_disabled(): the TFE
            # runner writes a frozen, paused workspace; others skip entirely.
            rc = self._build(all_comps, routing, args)
            if prune:
                # Prune diffs against every composition still in configs/ (enabled
                # OR disabled). Disabled is skipped, not deleted — only compositions
                # removed from configs/ are stale.
                self._prune_stale(all_comps, routing, dry_run=False)
            return rc

        if action == 'build' and dry_run and prune:
            self._prune_stale(all_comps, routing, dry_run=True)

        if action == 'destroy':
            console.print_warning("'destroy' is not yet implemented.")

        return 0

    # ── graph walk ────────────────────────────────────────────────────────────

    def _walk_compositions(self, root):
        """
        Recursively walk root, returning (comp_type, comp_path) for every
        composition=* directory found at any depth.
        Does NOT recurse inside composition directories.
        """
        results = []
        try:
            entries = sorted(os.listdir(root))
        except PermissionError:
            return results

        for entry in entries:
            full = os.path.join(root, entry)
            if not os.path.isdir(full):
                continue
            if COMPOSITION_KEY + "=" in entry:
                comp_type = split_path(entry)[1]
                results.append((comp_type, full))
            else:
                results.extend(self._walk_compositions(full))

        return results

    def _partition_enabled_compositions(self, all_comps):
        """Load raw config once per composition; split enabled vs disabled."""
        enabled = []
        disabled = []
        for comp_type, comp_path in all_comps:
            raw_config = self.get_raw_config(comp_path, comp_type)
            if self.is_composition_enabled(raw_config):
                enabled.append((comp_type, comp_path))
            else:
                disabled.append((comp_type, comp_path))
        return enabled, disabled

    # ── build ─────────────────────────────────────────────────────────────────

    def _build(self, all_comps, routing, args):
        failed = []
        for comp_type, comp_path in all_comps:
            target_runner = routing.get(comp_type)
            if not target_runner:
                console.print_warning(
                    f"No runner for '{comp_type}' — skipping {os.path.relpath(comp_path)}\n"
                    f"  Add it to komposconfig.compositions.order.<runner>."
                )
                continue

            runner_class  = _get_runner_class(target_runner)
            dispatch_args = _build_default_dispatch_args(target_runner)
            if not runner_class or dispatch_args is None:
                logger.warning(f"Cannot dispatch '{comp_type}' to '{target_runner}' — skipping")
                continue

            # Fill in himl defaults
            _himl_parser = argparse.ArgumentParser()
            SubParserConfig.add_himl_arguments(None, _himl_parser)
            for k, v in vars(_himl_parser.parse_args([])).items():
                if not hasattr(dispatch_args, k):
                    setattr(dispatch_args, k, v)

            logger.info(f"[{target_runner}] {os.path.relpath(comp_path)}")
            try:
                runner = runner_class(self.kompos_config, comp_path, self.execute)
                runner.run_configuration(dispatch_args)
                runner.himl_args = dispatch_args
                comps, paths = runner.get_compositions()
                rc = runner._run_compositions_internal(dispatch_args, [], comps, paths)
                if rc != 0:
                    failed.append(comp_path)
            except Exception as e:
                logger.error(f"Failed: {comp_path}: {e}")
                failed.append(comp_path)

        if failed:
            print(f"\n  ✗ {len(failed)} composition(s) failed:")
            for p in failed:
                print(f"    - {os.path.relpath(p)}")
            return 1
        return 0

    # ── prune ─────────────────────────────────────────────────────────────────

    def _prune_stale(self, live_comps, routing, dry_run=False):
        """Remove generated artifact dirs for compositions no longer in configs/.

        ``live_comps`` must be every composition still present in configs/ —
        enabled AND disabled. Disabling a composition skips its generation but
        keeps it in the live set, so its artifacts are frozen, not pruned. Only
        compositions removed from configs/ entirely are treated as stale.
        """
        live_instances = {}
        for comp_type, comp_path in live_comps:
            runner_type = routing.get(comp_type)
            if not runner_type:
                continue
            try:
                raw = self.get_raw_config(comp_path, comp_type)
                inst = raw.get('composition', {}).get('instance', '')
                if not inst or '{{' in str(inst):
                    inst = raw.get('cluster', {}).get('fullName', '')
            except Exception:
                inst = ''
            if inst:
                live_instances.setdefault(runner_type, set()).add(inst)

        base = self.kompos_config.get_kompos_setting('defaults.base_output_dir', './generated')
        pruned = []

        # A single instance dir under generated/<subdir>/ can be claimed by more than
        # one runner: generated/clusters/<name> holds both the tfe `cluster` output
        # (tfe/) and the `helm-values` output (helm-values/). A helm-only cluster has a
        # helm-values composition but no tfe cluster composition, so it lives only in
        # the helm live set. Prune against the UNION of every runner's live instances —
        # otherwise the tfe cluster pass would delete helm-only cluster dirs (and vice
        # versa). Only instances absent from configs/ entirely are stale.
        all_live = set()
        for instances in live_instances.values():
            all_live |= instances

        scanned_dirs = set()
        for runner_type, live in live_instances.items():
            for comp_type in self.kompos_config.composition_order(runner_type, default=[]):
                subdir = self.kompos_config.get_kompos_setting(
                    f'compositions.properties.{comp_type}.output_subdir', comp_type)
                target_dir = os.path.join(base, subdir)
                if target_dir in scanned_dirs or not os.path.isdir(target_dir):
                    continue
                scanned_dirs.add(target_dir)
                for entry in sorted(os.listdir(target_dir)):
                    if entry not in all_live:
                        stale = os.path.join(target_dir, entry)
                        if os.path.isdir(stale):
                            rel = os.path.relpath(stale)
                            if dry_run:
                                print(f"  (prune) {rel}")
                            else:
                                shutil.rmtree(stale)
                                console.print_warning(f"Pruned stale: {rel}")
                            pruned.append(stale)

        if not pruned:
            print("  No stale artifacts to prune.")

    # ── routing ───────────────────────────────────────────────────────────────

    def _build_routing_map(self):
        routing = {}
        for runner_type in ['tfe', 'helm', 'terraform', 'manual', 'external']:
            for comp_type in self.kompos_config.composition_order(runner_type, default=[]):
                if comp_type not in routing:
                    routing[comp_type] = runner_type
        return routing

    @staticmethod
    def execution(args, extra_args, default_output_path, composition, raw_config):
        return dict(command="")
