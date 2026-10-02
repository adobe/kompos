import argparse
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import kompos
import yaml
from himl.config_generator import ConfigGenerator, ConfigProcessor

from kompos.compile_context import CompileContext
from kompos.komposconfig import KomposConfig
from kompos.runner import GenericRunner
from kompos.runners.compile import CompileRunner


class CompileContextTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        previous = os.getcwd()
        self.addCleanup(os.chdir, previous)
        self.root = Path(temporary.name)
        os.chdir(self.root)
        self.path = Path("configs/cluster=one/composition=cluster")
        self.path.mkdir(parents=True)
        self.defaults = Path("configs/defaults.yaml")
        self.defaults.write_text(
            'source: original\n'
            'reference: "{{source}}"\n'
            'items: [base]\n'
            'nested: {base: true}\n'
            'composition: {instance: one}\n'
        )
        (self.path / "cluster.yaml").write_text(
            'items: [child]\nnested: {child: true}\n'
        )
        self.context = CompileContext()

    def process(self, processor=None, **kwargs):
        processor = processor or self.context.processor()
        return processor.process(
            path=str(self.path), skip_secrets=True, **kwargs
        )

    def test_shared_files_are_parsed_once_across_compositions(self):
        other = Path("configs/cluster=two/composition=cluster")
        other.mkdir(parents=True)
        (other / "cluster.yaml").write_text('composition: {instance: two}\n')
        original = ConfigGenerator.yaml_get_content
        reads = []

        def track(path):
            reads.append(os.path.abspath(path))
            return original(path)

        with patch.object(ConfigGenerator, "yaml_get_content", side_effect=track):
            first = self.process()
            second = self.context.processor().process(
                path=str(other), skip_secrets=True
            )
            self.process()
        self.assertEqual(reads.count(str(self.defaults.resolve())), 1)
        self.assertEqual(len(reads), 3)
        self.assertEqual(first["composition"]["instance"], "one")
        self.assertEqual(second["composition"]["instance"], "two")

    def test_unresolved_hierarchy_is_reused_for_output_variants(self):
        original = ConfigGenerator.process_hierarchy
        calls = []

        def track(generator):
            calls.append(generator.path)
            return original(generator)

        with patch.object(ConfigGenerator, "process_hierarchy", track):
            raw = self.process()
            filtered = self.process(filters=["reference"])
            unresolved = self.process(skip_interpolations=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual(filtered, {"reference": "original"})
        self.assertEqual(raw["reference"], "original")
        self.assertEqual(unresolved["reference"], "{{source}}")

    def test_cached_structures_are_isolated(self):
        original = self.process()
        original["nested"]["base"] = False
        original["items"].append("mutation")
        result = self.process()
        self.assertTrue(result["nested"]["base"])
        self.assertEqual(result["items"], ["base", "child"])
        other = Path("configs/cluster=two")
        other.mkdir()
        sibling = self.context.processor().process(
            path=str(other), skip_secrets=True
        )
        self.assertEqual(sibling["items"], ["base"])
        self.assertEqual(sibling["nested"], {"base": True})

    def test_file_edit_invalidates_hierarchy_and_preserves_unrelated_files(self):
        self.process()
        before = self.defaults.stat()
        self.defaults.write_text(self.defaults.read_text().replace("original", "modified"))
        # Same-size writes can retain both timestamps within one filesystem tick.
        os.utime(
            self.defaults,
            ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000),
        )
        self.assertGreater(self.defaults.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(self.defaults.stat().st_size, before.st_size)
        with patch.object(
                ConfigGenerator, "yaml_get_content",
                wraps=ConfigGenerator.yaml_get_content) as load:
            result = self.process()
        self.assertEqual(result["reference"], "modified")
        self.assertEqual(load.call_count, 1)

    def test_same_size_edit_with_restored_mtime_is_detected(self):
        self.process()
        before = self.defaults.stat()
        self.defaults.write_text(self.defaults.read_text().replace("original", "changed!"))
        os.utime(self.defaults, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(self.defaults.stat().st_size, before.st_size)
        self.assertEqual(self.process()["reference"], "changed!")

    def test_atomic_replacement_is_detected(self):
        self.process()
        replacement = Path("replacement.yaml")
        replacement.write_text(self.defaults.read_text().replace("original", "replaced"))
        replacement.replace(self.defaults)
        self.assertEqual(self.process()["reference"], "replaced")

    def test_file_addition_and_deletion_invalidate_hierarchy(self):
        self.process()
        added = self.path / "override.yaml"
        added.write_text("source: added\n")
        self.assertEqual(self.process()["reference"], "added")
        added.unlink()
        self.assertEqual(self.process()["reference"], "original")

    def test_new_yaml_directory_is_discovered(self):
        self.process()
        new = Path("configs/cluster=one/new")
        new.mkdir()
        (new / "values.yaml").write_text("source: new\n")
        self.assertEqual(
            self.context.processor().process(
                path=str(new), skip_secrets=True)["reference"], "new"
        )

    def test_removed_target_is_not_served_from_cache(self):
        empty = Path("configs/empty")
        empty.mkdir()
        processor = self.context.processor()
        processor.process(path=str(empty), skip_secrets=True)
        empty.rmdir()
        with self.assertRaises(FileNotFoundError):
            processor.process(path=str(empty), skip_secrets=True)

    def test_parse_errors_are_not_hidden_by_cache(self):
        self.process()
        self.defaults.write_text("invalid: [\n")
        with self.assertRaises(yaml.YAMLError) as error:
            self.process()
        self.assertIn("expected", str(error.exception))
        self.defaults.write_text("source: repaired\n")
        self.assertEqual(self.process()["source"], "repaired")

    def test_merge_strategies_have_separate_snapshots(self):
        appended = self.process(
            type_strategies=[(list, ["append"]), (dict, ["merge"])]
        )
        replaced = self.process(
            type_strategies=[(list, ["override"]), (dict, ["merge"])]
        )
        self.assertEqual(appended["items"], ["base", "child"])
        self.assertEqual(replaced["items"], ["child"])

    def test_filters_exclusions_and_output_match_uncached_processor(self):
        Path("outputs").mkdir()
        options = [
            {},
            {"filters": ["reference", "nested"]},
            {"exclude_keys": ["source"], "filters": ["nested"]},
            {"skip_interpolations": True},
            {"enclosing_key": "config"},
            {"multi_line_string": True},
        ]
        for index, kwargs in enumerate(options):
            with self.subTest(options=kwargs):
                expected = self.process(
                    ConfigProcessor(), output_file=f"outputs/expected-{index}.yaml", **kwargs
                )
                actual = self.process(output_file=f"outputs/actual-{index}.yaml", **kwargs)
                self.assertEqual(actual, expected)
                self.assertEqual(
                    Path(f"outputs/actual-{index}.yaml").read_bytes(),
                    Path(f"outputs/expected-{index}.yaml").read_bytes(),
                )

    def test_environment_resolution_is_not_cached(self):
        self.defaults.write_text('value: "{{env(COMPILE_CACHE_TEST)}}"\n')
        with patch.dict(os.environ, {"COMPILE_CACHE_TEST": "first"}):
            expected = self.process(ConfigProcessor())
            self.assertEqual(self.process(), expected)
            self.assertEqual(expected["value"], "first")
        with patch.dict(os.environ, {"COMPILE_CACHE_TEST": "second"}):
            expected = self.process(ConfigProcessor())
            self.assertEqual(self.process(), expected)
            self.assertEqual(expected["value"], "second")

    def test_dynamic_inputs_are_evaluated_on_every_request(self):
        calls = []

        def add_dynamic(generator):
            calls.append(generator.path)
            generator.generated_data["dynamic"] = len(calls)

        with patch.object(ConfigGenerator, "add_dynamic_data", add_dynamic):
            self.assertEqual(self.process()["dynamic"], 1)
            self.assertEqual(self.process()["dynamic"], 2)

    def test_resolved_secrets_do_not_enter_shared_cache(self):
        calls = []

        def resolve_secrets(generator, profile):
            calls.append(profile)
            generator.generated_data["secret"] = f"value-{len(calls)}"

        with patch.object(ConfigGenerator, "resolve_secrets", resolve_secrets):
            first = self.context.processor().process(path=str(self.path))
            second = self.context.processor().process(path=str(self.path))
        self.assertEqual(first["secret"], "value-1")
        self.assertEqual(second["secret"], "value-2")
        self.assertNotIn("secret", self.process())

    def test_nested_interpolation_aliases_and_serialization_match(self):
        self.defaults.write_text(
            'source: original\n'
            'selection: alpha\n'
            'mapping: {alpha: {value: "{{source}}"}}\n'
            'nested_reference: "{{mapping.{{selection}}.value}}"\n'
            'shared: &shared {value: "{{source}}"}\n'
            'alias: *shared\n'
            'multiline: |\n  first line\n  second line\n'
            'escaped: "{{`source`}}"\n'
        )
        for fmt in ("yaml", "json"):
            with self.subTest(format=fmt):
                expected_stream = StringIO()
                with redirect_stdout(expected_stream):
                    expected = self.process(
                        ConfigProcessor(), print_data=True, output_format=fmt,
                        multi_line_string=True,
                    )
                for _ in range(2):
                    actual_stream = StringIO()
                    with redirect_stdout(actual_stream):
                        actual = self.process(
                            print_data=True, output_format=fmt, multi_line_string=True
                        )
                    self.assertEqual(actual, expected)
                    self.assertEqual(actual_stream.getvalue(), expected_stream.getvalue())
                    self.assertEqual(actual["nested_reference"], "original")

    def test_raw_metadata_cache_observes_plugin_mutations(self):
        runner = GenericRunner(None, str(self.path), None, "test")
        runner.set_compile_context(self.context)
        first = runner.get_raw_config(str(self.path), "cluster")
        generated = self.path.parent / "generated.yaml"
        generated.write_text("composition: {enabled: false}\nsource: plugin\n")
        updated = runner.get_raw_config(str(self.path), "cluster")
        self.assertEqual(first["reference"], "original")
        self.assertEqual(updated["reference"], "plugin")
        self.assertFalse(runner.is_composition_enabled(updated))
        generated.unlink()
        self.assertTrue(runner.is_composition_enabled(
            runner.get_raw_config(str(self.path), "cluster")
        ))

    def test_context_lifetime_and_standalone_runner(self):
        runner = GenericRunner(None, str(self.path), None, "test")
        self.assertIsNone(runner.compile_context)
        self.assertIs(type(runner.config_processor), ConfigProcessor)
        runner.set_compile_context(self.context)
        runner.get_raw_config(str(self.path), "cluster")
        runner.set_compile_context(None)
        self.assertFalse(runner._raw_config_cache)
        self.assertFalse(runner._raw_config_versions)
        self.assertIs(type(runner.config_processor), ConfigProcessor)

    def test_cache_is_separate_for_each_working_directory(self):
        self.process()
        other = self.root / "other"
        (other / self.path).mkdir(parents=True)
        (other / self.defaults).write_text("source: other\n")
        os.chdir(other)
        self.assertEqual(self.process()["source"], "other")
        os.chdir(self.root)
        self.assertEqual(self.process()["source"], "original")

    def test_compile_shares_context_and_releases_it(self):
        runner = CompileRunner(None, str(self.path), None)
        contexts = []

        def build(*args):
            contexts.append(runner.compile_context)
            return 0

        with patch.object(runner, "_run_with_context", build):
            runner.run(argparse.Namespace(), [])
            self.assertIsNone(runner.compile_context)
            runner.run(argparse.Namespace(), [])
        self.assertIsNot(contexts[0], contexts[1])
        with patch.object(runner, "_run_with_context", side_effect=RuntimeError("failed")):
            with self.assertRaises(RuntimeError):
                runner.run(argparse.Namespace(), [])
        self.assertIsNone(runner.compile_context)

    def test_compile_dispatch_observes_plugin_changes_before_pruning(self):
        class Settings:
            def composition_order(self, runner, default=None):
                return ["cluster"] if runner == "manual" else (default or [])

            def build_order(self):
                return []

        contexts = []
        owner = self

        class MutatingRunner(GenericRunner):
            def __init__(self, config, path, execute):
                super().__init__(config, path, execute, "manual")

            def get_compositions(self):
                return ["cluster"], {"cluster": str(owner.path)}

            def _run_compositions_internal(self, *args):
                contexts.append(self.compile_context)
                generated = owner.path.parent / "generated.yaml"
                generated.write_text("composition: {instance: after-plugin}\n")
                return 0

        runner = CompileRunner(Settings(), str(self.path), None)

        def prune(compositions, routing, dry_run):
            self.assertEqual(
                runner.get_raw_config(str(self.path), "cluster")["composition"]["instance"],
                "after-plugin",
            )
            self.assertIs(contexts[0], runner.compile_context)

        with patch("kompos.runners.compile._get_runner_class", return_value=MutatingRunner), \
                patch.object(runner, "_prune_stale", prune), \
                redirect_stdout(StringIO()):
            self.assertEqual(
                runner.run(argparse.Namespace(action="build", prune=True, dry_run=False), []),
                0,
            )
        self.assertIsNone(runner.compile_context)

    def _assert_external_plugin_mutation(self, existing_input):
        generated = self.path.parent / "generated.yaml"
        if existing_input:
            generated.write_text("source: original\n")
        producer = self.path.parent / "composition=mutate"
        producer.mkdir()
        fixtures = Path(__file__).resolve().parent / "fixtures"
        (producer / "plugin.yaml").write_text(yaml.safe_dump({
            "composition": {
                "external": {
                    "entrypoint": "compile_mutating_plugin:mutate",
                    "pythonpath": [str(fixtures)],
                    "inputs": ["source"],
                    "outputs": [{
                        "path_key": "write_path",
                        "result_key": "body",
                        "format": "yaml",
                    }],
                },
            },
        }))
        (self.path / "cluster.yaml").write_text(yaml.safe_dump({
            "composition": {
                "instance": "{{reference}}",
                "output_subdir": "outputs",
                "files": [{
                    "path": "result.yaml",
                    "content": {"value": "{{reference}}"},
                }],
            },
        }))
        settings_file = Path(".komposconfig.yaml")
        settings_file.write_text(yaml.safe_dump({
            "komposconfig": {
                "terraform": {},
                "defaults": {"base_output_dir": "generated"},
                "compositions": {
                    "order": {"external": ["mutate"], "manual": ["cluster"]},
                    "build_order": [
                        {"runner": "external", "type": "mutate"},
                        {"runner": "manual", "type": "cluster"},
                    ],
                    "properties": {
                        "mutate": {"output_subdir": "outputs"},
                        "cluster": {"output_subdir": "outputs"},
                    },
                },
            },
        }))
        self.addCleanup(sys.modules.pop, "compile_mutating_plugin", None)
        with patch.object(KomposConfig, "DEFAULT_PATHS", [str(settings_file)]):
            settings = KomposConfig(argparse.Namespace(), str(Path(kompos.__file__).parent))
        runner = CompileRunner(settings, "configs", lambda command: 0)
        partition = runner._partition_enabled_compositions

        def check_warmed_metadata(compositions):
            result = partition(compositions)
            raw = runner.get_raw_config(str(self.path), "cluster")
            self.assertEqual(raw["reference"], "original")
            self.assertEqual(raw["composition"]["instance"], "original")
            self.assertEqual(generated.exists(), existing_input)
            return result

        with patch.object(
                runner, "_partition_enabled_compositions",
                side_effect=check_warmed_metadata) as metadata, \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(
                runner.run(argparse.Namespace(action="build", prune=True, dry_run=False), []),
                0,
            )
        metadata.assert_called_once()
        self.assertEqual(yaml.safe_load(generated.read_text()), {"source": "original-changed"})
        output = Path("generated/outputs/original-changed/result.yaml")
        self.assertEqual(yaml.safe_load(output.read_text()), {"value": "original-changed"})
        self.assertFalse(Path("generated/outputs/original").exists())
        self.assertIsNone(runner.compile_context)

    def test_external_plugin_rewrites_cached_input_during_compile(self):
        self._assert_external_plugin_mutation(existing_input=True)

    def test_external_plugin_creates_input_after_metadata_is_cached(self):
        self._assert_external_plugin_mutation(existing_input=False)


class CompileProgressTests(unittest.TestCase):
    def test_discovery_and_metadata_status_precede_loading(self):
        path = "configs/cluster=one/composition=cluster"
        compositions = [("cluster", path)]
        runner = CompileRunner(None, "configs", None)
        stderr = StringIO()
        stdout = StringIO()

        def walk(root):
            self.assertEqual(root, "configs")
            self.assertEqual(
                stderr.getvalue(),
                "Discovering compositions under configs...\n",
            )
            return compositions

        def load(comp_path, comp_type):
            self.assertEqual((comp_type, comp_path), compositions[0])
            self.assertEqual(
                stderr.getvalue().splitlines(),
                [
                    "Discovering compositions under configs...",
                    "Discovered 1 composition(s).",
                    "Loading composition metadata...",
                    f"Loading composition metadata [1/1]: {path}",
                ],
            )
            self.assertEqual(stdout.getvalue(), "")
            return {"composition": {"enabled": True}}

        with patch.object(runner, "run_configuration"), \
                patch.object(runner, "_build_routing_map", return_value={"cluster": "manual"}), \
                patch.object(runner, "_walk_compositions", side_effect=walk), \
                patch.object(runner, "get_raw_config", side_effect=load) as metadata, \
                patch.object(runner, "_build") as build, \
                redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(
                runner.run(argparse.Namespace(action="build", dry_run=True), []), 0
            )
        metadata.assert_called_once_with(path, "cluster")
        build.assert_not_called()
        self.assertIn(f"[manual] {path}  (dry-run)", stdout.getvalue())
        self.assertNotIn("Discovering", stdout.getvalue())
        self.assertNotIn("Loading composition metadata", stdout.getvalue())
        self.assertIsNone(runner.compile_context)

    def test_metadata_reports_first_every_tenth_and_last_before_loading(self):
        cases = [
            (0, []),
            (1, [1]),
            (10, [1, 10]),
            (11, [1, 10, 11]),
            (20, [1, 10, 20]),
            (21, [1, 10, 20, 21]),
        ]
        for total, milestones in cases:
            with self.subTest(total=total):
                runner = CompileRunner(None, "configs", None)
                compositions = [
                    ("cluster", f"configs/cluster={index}/composition=cluster")
                    for index in range(1, total + 1)
                ]
                stderr = StringIO()
                stdout = StringIO()
                expected = []
                loaded = []

                def load(comp_path, comp_type):
                    index = len(loaded) + 1
                    if index in milestones:
                        expected.append(
                            f"Loading composition metadata [{index}/{total}]: {comp_path}"
                        )
                    self.assertEqual(stderr.getvalue().splitlines(), expected)
                    loaded.append((comp_type, comp_path))
                    return {"composition": {"enabled": index % 2 == 1}}

                with patch.object(runner, "get_raw_config", side_effect=load), \
                        redirect_stdout(stdout), redirect_stderr(stderr):
                    enabled, disabled = runner._partition_enabled_compositions(compositions)
                self.assertEqual(loaded, compositions)
                self.assertEqual(enabled, compositions[::2])
                self.assertEqual(disabled, compositions[1::2])
                self.assertEqual(stderr.getvalue().splitlines(), expected)
                self.assertEqual(stdout.getvalue(), "")

    def test_empty_discovery_reports_zero_without_loading_metadata(self):
        runner = CompileRunner(None, "configs", None)
        stderr = StringIO()
        stdout = StringIO()
        with patch.object(runner, "run_configuration"), \
                patch.object(runner, "_build_routing_map", return_value={}), \
                patch.object(runner, "_walk_compositions", return_value=[]), \
                patch.object(runner, "_partition_enabled_compositions") as partition, \
                redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(runner.run(argparse.Namespace(), []), 0)
        self.assertEqual(
            stderr.getvalue().splitlines(),
            ["Discovering compositions under configs...", "Discovered 0 composition(s)."],
        )
        partition.assert_not_called()
        self.assertIn("No compositions found under the given path.", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
