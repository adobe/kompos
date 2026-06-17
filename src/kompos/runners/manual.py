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

from kompos.parser import SubParserConfig
from kompos.runner import GenericRunner
from kompos.helpers import console

logger = logging.getLogger(__name__)

RUNNER_TYPE = "manual"


class ManualParserConfig(SubParserConfig):
    def get_name(self):
        return RUNNER_TYPE

    def get_help(self):
        return 'Materialize manually-declared files for a composition (no external infra)'

    def configure(self, parser):
        self.add_himl_arguments(parser)
        return parser

    def get_epilog(self):
        return '''
Examples:
  # Write the files declared under composition.files for a composition
  kompos configs/.../cluster=foo/composition=manual manual generate

A manual composition owns hand-defined artifacts that have no upstream generator
(e.g. a mock terraform-outputs file for a cluster whose infra lives elsewhere).
Declaring them as a composition makes them config-as-code and prune-aware instead
of stray hand-edited files in the generated tree:

  composition:
    type: manual
    instance: "{{cluster.fullName}}"
    files:
      - path: terraform-outputs/tfe-outputs.yaml
        from_key: tf_generated      # copy this config subtree as the file body
      - path: notes/info.yaml
        content: { any: inline-yaml }   # or embed the body inline
'''


class ManualRunner(GenericRunner):
    """
    Writes the files declared under ``composition.files`` for a composition.

    Each entry is ``{path, from_key|content}``:
      - ``path``      relative to the composition instance dir
                      (``<base_output_dir>/<output_subdir>/<instance>/<path>``)
      - ``from_key``  dotted key snapshotted into the file *under its leaf key name*
                      (``from_key: tf_generated`` → file body ``{tf_generated: <value>}``),
                      so the file round-trips back into layered config when re-merged
      - ``content``   inline body, written verbatim (used when ``from_key`` is absent)

    ``output_subdir`` comes from ``composition.output_subdir`` (default ``clusters``),
    matching where the tfe/helm runners place per-instance artifacts.
    """

    def __init__(self, kompos_config, config_path, execute):
        super(ManualRunner, self).__init__(kompos_config, config_path, execute, RUNNER_TYPE)

    def run_configuration(self, args):
        self.configure_passive()

    def execution_configuration(self, composition, config_path, default_output_path, raw_config,
                                filtered_keys, excluded_keys):
        instance = self.require_composition_instance(raw_config)
        if not instance:
            return 1

        files = self.get_nested_value(raw_config, 'composition.files') or []
        if not files:
            console.print_warning(
                f"Manual composition '{composition}' declares no composition.files — nothing to write."
            )
            return 0

        subdir = self.get_nested_value(raw_config, 'composition.output_subdir')
        instance_dir = self.instance_output_dir(instance, subdir)

        written_paths = []
        for spec in files:
            rel_path = spec.get('path')
            if not rel_path:
                console.print_warning("Skipping composition.files entry with no 'path'.")
                continue
            body = spec.get('content')
            if body is None and spec.get('from_key'):
                key = spec['from_key']
                value = self.get_nested_value(raw_config, key)
                # Snapshot under the leaf key name so the file re-merges into layered
                # config at the same path (from_key: tf_generated → {tf_generated: ...}).
                body = {key.split('.')[-1]: value} if value is not None else {}
            if body is None:
                body = {}

            output_file = os.path.join(instance_dir, rel_path)
            self.write_structured_file(output_file, body, fmt=spec.get('format'))
            written_paths.append(output_file)
            console.print_file_generation("manual", output_file)

        # File-level prune: drop files this composition wrote on a prior run but
        # no longer declares (only under generated/; tracked in its own manifest).
        self.prune_composition_outputs(instance_dir, written_paths)

        return 0

    @staticmethod
    def execution(args, extra_args, default_output_path, composition, raw_config):
        """No external command — files are written in execution_configuration."""
        return dict(command="")
