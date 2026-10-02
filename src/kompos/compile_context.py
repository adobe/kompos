# Copyright 2026 Adobe. All rights reserved.
# This file is licensed to you under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License. You may obtain a copy
# of the License at http://www.apache.org/licenses/LICENSE-2.0

from copy import deepcopy
import os

from himl.config_generator import ConfigGenerator, ConfigProcessor


class CompileContext:
    """Shared input cache for one compile; never cache resolved or secret data."""

    def __init__(self):
        self._yaml = {}
        self._hierarchies = {}

    @staticmethod
    def _file_version(path):
        stat = os.stat(path)
        return (
            stat.st_dev, stat.st_ino, stat.st_size,
            stat.st_mtime_ns, stat.st_ctime_ns,
        )

    def input_version(self, hierarchy):
        # Rediscover directories on each request so added/deleted YAML participates.
        return tuple(
            tuple((path, self._file_version(path)) for path in files)
            for files in hierarchy
        )

    def load_yaml(self, path):
        key = os.path.abspath(path)
        version = self._file_version(key)
        cached = self._yaml.get(key)
        if cached is None or cached[0] != version:
            data = ConfigGenerator.yaml_get_content(path)
            self._yaml[key] = (version, data)
        else:
            data = cached[1]
        # HIML merges and interpolates in-place, including values from YAML aliases.
        return deepcopy(data)

    def process_hierarchy(self, generator):
        target = os.path.join(generator.cwd, generator.path)
        if not os.path.exists(target):
            raise FileNotFoundError(f"Path does not exist: {target}")
        key = (
            generator.cwd, generator.path,
            tuple((kind, tuple(strategies)) for kind, strategies in generator.type_strategies),
            tuple(generator.fallback_strategies),
            tuple(generator.type_conflict_strategies),
        )
        version = self.input_version(generator.hierarchy)
        cached = self._hierarchies.get(key)
        if cached is None or cached[0] != version:
            ConfigGenerator.process_hierarchy(generator)
            self._hierarchies[key] = (version, deepcopy(generator.generated_data))
        else:
            generator.generated_data = deepcopy(cached[1])

    def processor(self):
        return _CompileConfigProcessor(self)


class _CompileConfigGenerator(ConfigGenerator):
    def __init__(self, context, *args):
        self.context = context
        super().__init__(*args)

    def yaml_get_content(self, path):
        return self.context.load_yaml(path)

    def process_hierarchy(self):
        self.context.process_hierarchy(self)


class _CompileConfigProcessor(ConfigProcessor):
    def __init__(self, context):
        self.context = context

    def _create_and_initialize_generator(
            self, cwd, path, multi_line_string, allow_unicode, type_strategies,
            fallback_strategies, type_conflict_strategies):
        generator = _CompileConfigGenerator(
            self.context, cwd, path, multi_line_string, allow_unicode,
            type_strategies, fallback_strategies, type_conflict_strategies,
        )
        generator.process_hierarchy()
        return generator

    def input_version(self, path):
        path = self.get_relative_path(path)
        target = os.path.join(os.getcwd(), path)
        if not os.path.exists(target):
            raise FileNotFoundError(f"Path does not exist: {target}")
        generator = ConfigGenerator(
            os.getcwd(), path, False, False,
            [(list, ["append"]), (dict, ["merge"])], ["override"], ["override"],
        )
        return self.context.input_version(generator.hierarchy)
