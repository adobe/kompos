# Copyright 2026 Adobe. All rights reserved.
# This file is licensed to you under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License. You may obtain a copy
# of the License at http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software distributed under
# the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR REPRESENTATIONS
# OF ANY KIND, either express or implied. See the License for the specific language
# governing permissions and limitations under the License.

import importlib
import json
import logging
import os
import subprocess
import sys

import yaml

from kompos.parser import SubParserConfig
from kompos.runner import GenericRunner
from kompos.helpers import console

logger = logging.getLogger(__name__)

RUNNER_TYPE = "external"


class ExternalParserConfig(SubParserConfig):
    def get_name(self):
        return RUNNER_TYPE

    def get_help(self):
        return 'Run repo-local plugin code (Python entrypoint or subprocess) for a composition'

    def configure(self, parser):
        self.add_himl_arguments(parser)
        return parser

    def get_epilog(self):
        return '''
A light plugin host: Kompos owns discovery, the merged config context, enable/prune
and where files land. The plugin owns the transform. Kompos hands the plugin ONLY the
config keys it declares (nothing else), and writes back ONLY what the plugin returns.

  composition:
    type: external
    instance: "{{cell.fullName}}"
    external:
      # Pick ONE of entrypoint (in-process) or command (subprocess).
      entrypoint: "topology_carver.plugin:carve"   # "module:callable" on PYTHONPATH
      # command: ["python3", "scripts/carve_plugin.py"]   # language-agnostic subprocess
      pythonpath: [scripts/topology-carver]        # dirs prepended to sys.path (entrypoint mode)
      inputs:                                      # dotted config paths handed to the plugin
        - ipam_topology
        - account.ipam
        - cell.ipam
      output_subdir: cells                         # default: clusters
      outputs:                                     # what Kompos writes from the plugin result
        - path: cell_ipam.yaml                     # relative to <base>/<subdir>/<instance>/
          result_key: ledger                       # literal key of the result dict (optional)
          header_key: report                       # yaml only: result[report] (list[str]) written
                                                    #   as `# ...` comment lines before the body
          format: yaml                             # optional; inferred from extension

Plugin contract:
  Python entrypoint:  def carve(inputs: dict, context: dict) -> dict
    inputs   {declared_dotted_path: value}  — only declared keys, flat dotted keys
    context  {instance, composition, config_path, outputs}  — read-only metadata
    returns  dict keyed by output path (or result_key); a single output may also
             return the bare body (no keying). Keys are matched literally.
  Subprocess:  stdin  {"inputs": {...}, "context": {...}}  (JSON)
               stdout {"outputs": {"<declared path>": <body>, ...}}  (JSON)
               (single output may also emit the bare body dict on stdout)

IMPORTANT — context is path-local:
  Kompos only merges config along THIS composition's own path (its ancestors + self),
  never child paths. A plugin at composition=cell sees account/env/region/cell, NOT the
  child cluster=*/ configs. Declare inputs that exist at the composition's level.

Examples:
  kompos configs/.../cell=cell01/composition=ipam external generate
'''


class ExternalRunner(GenericRunner):
    """
    Plugin host runner.

    For a ``composition.type: external`` composition it:
      1. resolves the composition instance (output dir name),
      2. extracts the declared ``external.inputs`` (dotted paths) from the merged,
         path-local config into a flat ``{path: value}`` dict,
      3. invokes the plugin — an in-process Python ``entrypoint`` ("module:callable")
         or a ``command`` subprocess (JSON over stdin/stdout),
      4. writes the returned bodies to the declared ``external.outputs`` under
         ``<base_output_dir>/<output_subdir>/<instance>/<path>``.

    Kompos keeps ownership of discovery, the config context, enable/prune and output
    location; the plugin only transforms declared inputs into declared outputs. This
    keeps plugins free of file management and "which config file do I read" logic.
    """

    def __init__(self, kompos_config, config_path, execute):
        super(ExternalRunner, self).__init__(kompos_config, config_path, execute, RUNNER_TYPE)

    def run_configuration(self, args):
        self.validate_runner = False
        self.ordered_compositions = False
        self.reverse = False
        self.generate_output = False

    def execution_configuration(self, composition, config_path, default_output_path, raw_config,
                                filtered_keys, excluded_keys):
        instance = self.require_composition_instance(raw_config)
        if not instance:
            return 1

        spec = self.get_nested_value(raw_config, 'composition.external')
        if not spec or not isinstance(spec, dict):
            console.print_warning(
                f"External composition '{composition}' declares no composition.external — nothing to run."
            )
            return 0

        entrypoint = spec.get('entrypoint')
        command = spec.get('command')
        if not entrypoint and not command:
            console.print_error(
                "External composition is missing a plugin entrypoint",
                details=[
                    "  Set composition.external.entrypoint (\"module:callable\")",
                    "  or composition.external.command ([\"prog\", \"arg\", ...]).",
                    f"  Config path: {config_path}",
                ],
            )
            return 1
        if entrypoint and command:
            console.print_error(
                "External composition declares both entrypoint and command",
                details=["  Pick exactly one of composition.external.entrypoint / command."],
            )
            return 1

        outputs = spec.get('outputs') or []
        if not outputs:
            console.print_warning(
                f"External composition '{composition}' declares no composition.external.outputs — nothing to write."
            )
            return 0

        # Hand the plugin ONLY the declared inputs (flat dotted keys), nothing else.
        inputs = {}
        for key in (spec.get('inputs') or []):
            value = self.get_nested_value(raw_config, key)
            if value is None:
                console.print_warning(
                    f"External input '{key}' not found in config for '{instance}' — passing null."
                )
            inputs[key] = value

        context = {
            'instance': instance,
            'composition': composition,
            'config_path': config_path,
            'outputs': outputs,
        }

        try:
            if entrypoint:
                result = self._run_entrypoint(entrypoint, spec.get('pythonpath') or [], inputs, context)
            else:
                result = self._run_command(command, inputs, context)
        except Exception as e:
            console.print_error(
                f"External plugin failed for '{instance}'",
                details=[f"  {type(e).__name__}: {e}", f"  Config path: {config_path}"],
            )
            logger.debug("External plugin traceback", exc_info=True)
            return 1

        if not isinstance(result, dict):
            console.print_error(
                "External plugin returned a non-dict result",
                details=[f"  Got {type(result).__name__}; expected a mapping of output bodies."],
            )
            return 1

        base = self.kompos_config.get_kompos_setting('defaults.base_output_dir', './generated')
        # output_subdir may live on the external block or (for parity with the manual
        # runner) directly under composition; default matches the other runners.
        subdir = (spec.get('output_subdir')
                  or self.get_nested_value(raw_config, 'composition.output_subdir')
                  or 'clusters')
        instance_dir = os.path.join(base, subdir, instance)

        return self._write_outputs(outputs, result, instance_dir, single=len(outputs) == 1)

    # ── plugin invocation ───────────────────────────────────────────────────────

    def _run_entrypoint(self, entrypoint, pythonpath, inputs, context):
        """Import and call an in-process Python plugin "module.path:callable"."""
        if ':' not in entrypoint:
            raise ValueError(
                f"entrypoint must be 'module.path:callable', got {entrypoint!r}"
            )
        module_name, _, func_name = entrypoint.partition(':')

        # cwd is the root_path (kompos chdirs there at startup); add it plus any
        # declared pythonpath dirs so repo-local plugin modules import cleanly.
        added = []
        for p in [os.getcwd()] + [os.path.join(os.getcwd(), d) for d in pythonpath]:
            if p not in sys.path:
                sys.path.insert(0, p)
                added.append(p)
        try:
            module = importlib.import_module(module_name)
            func = getattr(module, func_name, None)
            if not callable(func):
                raise AttributeError(f"{module_name!r} has no callable {func_name!r}")
            logger.info(f"[external] entrypoint {entrypoint}")
            return func(inputs, context)
        finally:
            for p in added:
                try:
                    sys.path.remove(p)
                except ValueError:
                    pass

    def _run_command(self, command, inputs, context):
        """Run a subprocess plugin: JSON over stdin, JSON {"outputs": {...}} on stdout."""
        if isinstance(command, str):
            command = command.split()
        payload = json.dumps({'inputs': inputs, 'context': context})
        logger.info(f"[external] command {' '.join(command)}")
        proc = subprocess.run(
            command,
            input=payload,
            capture_output=True,
            text=True,
            cwd=os.getcwd(),
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"command exited {proc.returncode}: {proc.stderr.strip() or proc.stdout.strip()}"
            )
        out = proc.stdout.strip()
        if not out:
            raise RuntimeError("command produced no stdout (expected JSON)")
        parsed = json.loads(out)
        # Prefer the {"outputs": {...}} envelope; fall back to a bare body dict.
        if isinstance(parsed, dict) and 'outputs' in parsed and isinstance(parsed['outputs'], dict):
            return parsed['outputs']
        return parsed

    # ── output writing ──────────────────────────────────────────────────────────

    def _write_outputs(self, outputs, result, instance_dir, single):
        for spec in outputs:
            rel_path = spec.get('path')
            if not rel_path:
                console.print_warning("Skipping composition.external.outputs entry with no 'path'.")
                continue

            # Plugins key their result by a literal string: the output `path` by
            # default, or an explicit `result_key`. A single output may also return
            # the bare body (no keying) for convenience.
            key = spec.get('result_key') or rel_path
            if isinstance(result, dict) and key in result:
                body = result[key]
            elif isinstance(result, dict) and os.path.basename(rel_path) in result:
                body = result[os.path.basename(rel_path)]
            elif single:
                body = result
            else:
                body = None

            if body is None:
                console.print_error(
                    f"External plugin returned nothing for output '{rel_path}'",
                    details=[
                        "  Set composition.external.outputs[].result_key to a key the plugin returns,",
                        f"  or have the plugin key its result by the output path. Got keys: {list(result.keys())}",
                    ],
                )
                return 1

            # Optional comment header (yaml only): the plugin returns lines under
            # header_key; the runner writes them as `# ...` before the body so a
            # generated yaml file can carry a DO-NOT-EDIT banner / ASCII map.
            header = None
            header_key = spec.get('header_key')
            if header_key and isinstance(result, dict):
                header = result.get(header_key)

            fmt = (spec.get('format') or self.extract_format_from_extension(rel_path)).lower()
            output_file = os.path.join(instance_dir, rel_path)
            self.ensure_directory(output_file, is_file_path=True)
            with open(output_file, 'w') as f:
                if fmt == 'json':
                    if header:
                        console.print_warning(
                            f"Ignoring header_key for JSON output '{rel_path}' (JSON has no comments)."
                        )
                    json.dump(body, f, indent=2, sort_keys=False)
                    f.write('\n')
                else:
                    if header:
                        lines = header if isinstance(header, list) else str(header).splitlines()
                        for line in lines:
                            f.write(f"# {line}\n" if line else "#\n")
                    yaml.dump(body, f, default_flow_style=False, sort_keys=False)
            console.print_file_generation("external", output_file)

        return 0

    @staticmethod
    def execution(args, extra_args, default_output_path, composition, raw_config):
        """No external infra command — plugin runs in execution_configuration."""
        return dict(command="")
