"""Managed README generation for the helm runner.

Per-cluster ``README.md`` under helm-values output is always written. Deployment
inventory (also written to ``charts/{chart}/README.md``) is opt-in via
``helm.config.inventory`` in ``.komposconfig.yaml``.
"""

import glob
import logging
import os
import re

import yaml

logger = logging.getLogger(__name__)

_PLACEHOLDER = re.compile(r'\{([^}]+)\}')

# Process-wide cache: cluster metadata for inventory survives across helm generate
# invocations in one compile build (keyed by configs root + composition type).
_CLUSTER_CONFIG_CACHE = {}
_ENV_YAML_CACHE = {}
_PENDING_CHART_INVENTORY = {}

_INDEX_CACHE_FILENAME = '.kompos-inventory-cluster-index.yaml'

# Used when inventory.columns is not set (filesystem layout only).
_DEFAULT_INVENTORY_COLUMNS = [
    {
        'header': 'Cluster',
        'template': '`{cluster}`',
    },
    {
        'header': 'Symlink',
        'template': (
            '[`generated/{cluster}.yaml`]'
            '(../../generated/clusters/{cluster}/helm-values/{chart}.yaml)'
        ),
    },
]

_DEFAULT_CONFIG_FILTERS = ('env', 'cluster', 'composition', 'account', 'region', 'cell')

_DEFAULT_CONFIGS_MARKER = 'chart_registry.yaml'
_DEFAULT_CHART_REGISTRY_CHARTS_PATH = 'helm.charts'
_DEFAULT_CHART_LINKS_HEADING = 'Source & GitOps'
_DEFAULT_CHART_LINKS = [
    {
        'label': 'Helm chart',
        'key': 'chart_repo',
    },
    {
        'label': 'Version',
        'from_key': 'chart_repo',
        'path_suffix': 'version.yaml',
        'link_text': 'version.yaml',
    },
    {
        'label': 'ApplicationSet',
        'key': 'argocd_app',
    },
]

_CHART_REGISTRY_CACHE = {}


class HelmReadmeWriter:
    """Write kompos-managed README.md files for helm values output."""

    def __init__(self, runner):
        self._runner = runner
        self._template_cache = {}

    @staticmethod
    def cleanup_legacy_readme(generated_dir):
        """Remove README.md left under charts/{chart}/generated/ from older kompos versions."""
        if not generated_dir:
            return
        legacy_readme = os.path.join(generated_dir, 'README.md')
        if os.path.isfile(legacy_readme):
            os.remove(legacy_readme)

    def write_cluster_readme(self, argoapps_dir, cluster_name, chart_files):
        """Write per-cluster README (always — same as pre-0.12.3 helm generate behavior)."""
        self._preload_templates()
        charts_list = '\n'.join(f'  - `{name}.yaml`' for name in sorted(chart_files.keys()))
        cluster_readme = self._load_template('helm-readme.md').format(
            cluster_name=cluster_name,
            pipeline_diagram=self._render_pipeline_diagram(f'{cluster_name}.yaml'),
            charts_list=charts_list,
        )
        self._write_if_changed(os.path.join(argoapps_dir, 'README.md'), cluster_readme)

    def write_chart_inventory(self, charts_dir, chart_files, config_path=None,
                              composition=None, current_raw_config=None,
                              defer_chart_inventory=False):
        """Write per-chart README.md with deployment inventory (opt-in via ``helm.config.inventory``)."""
        if not self._runner.symlink_generated or not charts_dir:
            return

        mode = self._chart_inventory_refresh_mode()
        if mode == 'never':
            return

        _PENDING_CHART_INVENTORY[os.path.abspath(charts_dir)] = {
            'runner': self._runner,
            'composition': composition,
            'config_path': config_path,
            'current_raw_config': current_raw_config,
        }

        if mode == 'always':
            self._flush_chart_inventory_for_dir(os.path.abspath(charts_dir))
        elif mode == 'deferred' and not defer_chart_inventory:
            self.flush_pending_chart_inventory()

    def write_all(self, argoapps_dir, cluster_name, env_name, chart_files,
                  charts_dir=None, pruned_charts=None, config_path=None,
                  composition=None, current_raw_config=None,
                  defer_chart_inventory=False):
        """Write cluster README and (when inventory enabled) chart inventory READMEs."""
        self.write_cluster_readme(argoapps_dir, cluster_name, chart_files)
        self.write_chart_inventory(
            charts_dir, chart_files, config_path=config_path,
            composition=composition, current_raw_config=current_raw_config,
            defer_chart_inventory=defer_chart_inventory)

    @classmethod
    def flush_pending_chart_inventory(cls):
        """Write chart inventory READMEs once after all helm generate runs."""
        for charts_dir in list(_PENDING_CHART_INVENTORY.keys()):
            ctx = _PENDING_CHART_INVENTORY.get(charts_dir)
            if not ctx:
                continue
            HelmReadmeWriter(ctx['runner'])._flush_chart_inventory_for_dir(charts_dir)
        _PENDING_CHART_INVENTORY.clear()

    def _chart_inventory_refresh_mode(self):
        inv = self._inventory_config()
        return inv.get('refresh', inv.get('chart_readmes', 'deferred'))

    def _use_disk_index_cache(self):
        return self._inventory_config().get('cluster_index_cache', True)

    def _flush_chart_inventory_for_dir(self, charts_dir):
        self._preload_templates()
        ctx = _PENDING_CHART_INVENTORY.get(charts_dir, {})
        composition = ctx.get('composition')
        config_path = ctx.get('config_path')
        current_raw_config = ctx.get('current_raw_config')

        cluster_configs = {}
        if self._inventory_needs_cluster_configs():
            configs_root = self._find_configs_root(config_path)
            cluster_configs = self._get_cluster_configs(
                configs_root, composition, config_path, current_raw_config)

        chart_pipeline = self._render_pipeline_diagram('{cluster}.yaml')
        chart_tpl = self._template_cache['helm-chart-readme.md']

        configs_root = self._find_configs_root(config_path)
        for app_name in sorted(self._discover_charts_with_symlinks(charts_dir)):
            chart_dir = os.path.join(charts_dir, app_name)
            self._write_chart_inventory_readme(
                chart_dir, app_name, cluster_configs, chart_tpl, chart_pipeline,
                configs_root=configs_root)

    @staticmethod
    def _discover_charts_with_symlinks(charts_dir):
        if not os.path.isdir(charts_dir):
            return []
        return [
            name for name in os.listdir(charts_dir)
            if os.path.isdir(os.path.join(charts_dir, name, 'generated'))
        ]

    def _preload_templates(self):
        for name in (
            'helm-readme.md',
            'helm-chart-readme.md',
            'helm-pipeline-diagram.md',
            'helm-deployment-inventory-empty.md',
        ):
            self._load_template(name)

    def _inventory_config(self):
        return getattr(self._runner, 'inventory', None) or {}

    def _inventory_columns(self):
        return self._inventory_config().get('columns') or _DEFAULT_INVENTORY_COLUMNS

    def _inventory_group_by(self):
        return self._inventory_config().get('group_by')

    def _inventory_group_order(self):
        return self._inventory_config().get('group_order') or []

    def _table_columns(self):
        """Columns rendered in each inventory table (drops the group_by column when grouped)."""
        columns = self._inventory_columns()
        group_by = self._inventory_group_by()
        if not group_by:
            return columns
        group_template = '{' + group_by + '}'
        return [
            col for col in columns
            if col.get('template', '').strip() != group_template
        ]

    def _inventory_config_paths(self):
        paths = set()
        group_by = self._inventory_group_by()
        if group_by:
            paths.add(group_by)
        for column in self._inventory_columns():
            for key in _PLACEHOLDER.findall(column.get('template', '')):
                if key not in ('cluster', 'chart'):
                    paths.add(key)
        return paths

    def _inventory_needs_cluster_configs(self):
        return bool(self._inventory_config_paths())

    def _config_filters(self):
        return tuple(self._inventory_config().get('config_filters') or _DEFAULT_CONFIG_FILTERS)

    def _templates_dir(self):
        return os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'templates')

    def _load_template(self, name):
        if name not in self._template_cache:
            with open(os.path.join(self._templates_dir(), name)) as f:
                self._template_cache[name] = f.read()
        return self._template_cache[name]

    def _render_pipeline_diagram(self, cluster_override_label):
        return self._load_template('helm-pipeline-diagram.md').format(
            bridge_filename=self._runner.bridge_filename,
            overrides_subdir=self._runner.overrides_subdir,
            cluster_override_label=cluster_override_label,
        )

    @staticmethod
    def _write_if_changed(path, content):
        if os.path.isfile(path):
            with open(path) as f:
                if f.read() == content:
                    return
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        with open(path, 'w') as f:
            f.write(content)

    def _list_chart_override_files(self, chart_dir):
        overrides_dir = os.path.join(chart_dir, self._runner.overrides_subdir)
        if not os.path.isdir(overrides_dir):
            return []
        return sorted(f for f in os.listdir(overrides_dir) if f.endswith('.yaml'))

    def _format_override_files_list(self, override_files):
        if not override_files:
            return '  - _(none — bridge only)_'
        return '\n'.join(
            f'  - `{self._runner.overrides_subdir}/{name}`' for name in override_files)

    def _list_generated_cluster_names(self, per_chart_dir):
        if not os.path.isdir(per_chart_dir):
            return []
        return sorted(
            name[:-5] for name in os.listdir(per_chart_dir)
            if name.endswith('.yaml')
        )

    def _configs_marker(self):
        return self._inventory_config().get('configs_marker', _DEFAULT_CONFIGS_MARKER)

    def _chart_links_specs(self):
        inventory = self._inventory_config()
        if 'chart_links' in inventory:
            return inventory['chart_links'] or []
        return _DEFAULT_CHART_LINKS

    def _find_configs_root(self, config_path):
        marker = self._configs_marker()
        if not config_path:
            return None
        path = os.path.abspath(config_path)
        while True:
            if os.path.isfile(os.path.join(path, marker)):
                return path
            parent = os.path.dirname(path)
            if parent == path:
                return None
            path = parent

    @staticmethod
    def _find_env_dir(config_path):
        path = os.path.abspath(config_path)
        while True:
            if os.path.basename(path).startswith('env='):
                return path
            parent = os.path.dirname(path)
            if parent == path:
                return None
            path = parent

    @staticmethod
    def _composition_type(composition, inventory_config):
        if inventory_config.get('composition_type'):
            return inventory_config['composition_type']
        if composition is None:
            return None
        if hasattr(composition, 'type'):
            return composition.type
        return str(composition)

    def _find_helm_values_roots(self, configs_root, comp_type):
        pattern = os.path.join(configs_root, '**', f'composition={comp_type}', 'helm.yaml')
        return sorted(os.path.dirname(path) for path in glob.glob(pattern, recursive=True))

    def _index_cache_path(self, configs_root):
        return os.path.join(configs_root, _INDEX_CACHE_FILENAME)

    def _index_cache_sources(self, configs_root, comp_type):
        sources = []
        for root in self._find_helm_values_roots(configs_root, comp_type):
            helm_yaml = os.path.join(root, 'helm.yaml')
            if os.path.isfile(helm_yaml):
                sources.append(helm_yaml)
            env_dir = self._find_env_dir(root)
            if env_dir:
                env_yaml = os.path.join(env_dir, 'env.yaml')
                if os.path.isfile(env_yaml):
                    sources.append(env_yaml)
        return sorted(set(sources))

    @staticmethod
    def _snapshot_sources(source_paths):
        snapshot = []
        for path in source_paths:
            if os.path.isfile(path):
                snapshot.append({'path': path, 'mtime': os.path.getmtime(path)})
        return snapshot

    @staticmethod
    def _sources_match_snapshot(snapshot):
        for entry in snapshot:
            path = entry['path']
            if not os.path.isfile(path):
                return False
            if os.path.getmtime(path) != entry['mtime']:
                return False
        return True

    def _load_disk_cluster_index(self, cache_path):
        try:
            with open(cache_path) as f:
                payload = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError):
            return None
        snapshot = payload.get('sources') or []
        if not self._sources_match_snapshot(snapshot):
            return None
        clusters = payload.get('clusters')
        return clusters if isinstance(clusters, dict) else None

    def _save_disk_cluster_index(self, cache_path, clusters, source_paths):
        payload = {
            'sources': self._snapshot_sources(source_paths),
            'clusters': clusters,
        }
        with open(cache_path, 'w') as f:
            yaml.safe_dump(payload, f, default_flow_style=False, sort_keys=False)

    def _get_cluster_configs(self, configs_root, composition,
                             current_config_path=None, current_raw_config=None):
        inventory_config = self._inventory_config()
        comp_type = self._composition_type(composition, inventory_config)
        cache_key = (configs_root, comp_type, tuple(sorted(self._inventory_config_paths())))
        if cache_key in _CLUSTER_CONFIG_CACHE:
            return _CLUSTER_CONFIG_CACHE[cache_key]

        index = None
        cache_path = self._index_cache_path(configs_root)
        source_paths = self._index_cache_sources(configs_root, comp_type)
        if self._use_disk_index_cache() and configs_root:
            index = self._load_disk_cluster_index(cache_path)

        if index is None:
            index = self._build_cluster_config_index(
                configs_root, composition, current_config_path, current_raw_config)
            if self._use_disk_index_cache() and configs_root and index:
                try:
                    self._save_disk_cluster_index(cache_path, index, source_paths)
                except OSError:
                    logger.debug('Could not write inventory cluster index cache', exc_info=True)

        _CLUSTER_CONFIG_CACHE[cache_key] = index
        return index

    def _load_env_config(self, env_dir):
        if not env_dir:
            return {}
        if env_dir not in _ENV_YAML_CACHE:
            env_yaml = os.path.join(env_dir, 'env.yaml')
            _ENV_YAML_CACHE[env_dir] = self._runner.load_yaml_file(env_yaml) or {}
        return _ENV_YAML_CACHE[env_dir]

    def _load_metadata_config(self, root, composition, current_config_path, current_raw_config):
        """Load the smallest config slice needed for inventory column templates."""
        paths = self._inventory_config_paths()
        root_abs = os.path.abspath(root)

        if (current_config_path and current_raw_config
                and root_abs == os.path.abspath(current_config_path)):
            cluster = self._runner.get_composition_name(current_raw_config)
            if not cluster:
                return None, None
            if paths and all(p.startswith('env.') for p in paths):
                env_dir = self._find_env_dir(root)
                return cluster, self._load_env_config(env_dir)
            return cluster, self._slice_config(current_raw_config, paths)

        if paths and all(p.startswith('env.') for p in paths):
            env_dir = self._find_env_dir(root)
            name_meta = self._runner.generate_config(
                root,
                filters=self._config_filters(),
                skip_interpolation_validation=True,
                skip_secrets=True,
                silent=True,
            )
            cluster = self._runner.get_composition_name(name_meta)
            if not cluster:
                return None, None
            return cluster, self._load_env_config(env_dir)

        meta = self._runner.generate_config(
            root,
            filters=self._config_filters(),
            skip_interpolation_validation=True,
            skip_secrets=True,
            silent=True,
        )
        cluster = self._runner.get_composition_name(meta)
        if not cluster:
            return None, None
        return cluster, self._slice_config(meta, paths)

    def _build_cluster_config_index(self, configs_root, composition,
                                    current_config_path=None, current_raw_config=None):
        """Map cluster fullName → config slice for inventory column templates."""
        index = {}
        inventory_config = self._inventory_config()
        comp_type = self._composition_type(composition, inventory_config)
        if not configs_root or not comp_type:
            return index

        roots = self._find_helm_values_roots(configs_root, comp_type)
        for root in roots:
            try:
                cluster, config_slice = self._load_metadata_config(
                    root, composition, current_config_path, current_raw_config)
            except Exception:
                logger.debug(f"Skipping cluster index for {root}", exc_info=True)
                continue
            if cluster and config_slice is not None:
                index[cluster] = config_slice
        return index

    @staticmethod
    def _slice_config(raw, paths):
        """Keep only nested keys referenced by inventory column templates."""
        if not paths:
            return raw
        sliced = {}
        for path in paths:
            value = raw
            for part in path.split('.'):
                if not isinstance(value, dict):
                    value = None
                    break
                value = value.get(part)
            if value is None:
                continue
            dest = sliced
            parts = path.split('.')
            for part in parts[:-1]:
                dest = dest.setdefault(part, {})
            dest[parts[-1]] = value
        return sliced

    @staticmethod
    def _resolve_template(template, cluster, chart, cluster_config, runner):
        def repl(match):
            key = match.group(1)
            if key == 'cluster':
                return cluster
            if key == 'chart':
                return chart
            if cluster_config is None:
                return ''
            value = runner.get_nested_value(cluster_config, key)
            return '' if value is None else str(value)

        return _PLACEHOLDER.sub(repl, template)

    @staticmethod
    def _cell_is_empty(cell):
        if not cell or not cell.strip():
            return True
        return '{' in cell and '}' in cell

    def _cluster_group(self, cluster, cluster_config):
        group_by = self._inventory_group_by()
        if not group_by:
            return None
        value = self._runner.get_nested_value(cluster_config or {}, group_by)
        if value is None or str(value).strip() == '':
            return '—'
        return str(value)

    def _format_inventory_table(self, chart_name, cluster_names, cluster_configs, columns):
        if not cluster_names:
            return ''
        headers = [col['header'] for col in columns]
        header_row = '| ' + ' | '.join(headers) + ' |'
        separator = '|' + '|'.join('---' for _ in headers) + '|'
        rows = []
        for cluster in sorted(cluster_names):
            config = cluster_configs.get(cluster)
            cells = []
            for column in columns:
                cell = self._resolve_template(
                    column['template'], cluster, chart_name, config, self._runner)
                if column.get('empty') and self._cell_is_empty(cell):
                    cell = column['empty']
                cells.append(cell)
            rows.append('| ' + ' | '.join(cells) + ' |')
        return '\n'.join([header_row, separator] + rows)

    def _format_deployment_inventory(self, chart_name, cluster_names, cluster_configs=None):
        if not cluster_names:
            return self._load_template('helm-deployment-inventory-empty.md').strip()

        cluster_configs = cluster_configs or {}
        columns = self._table_columns()
        group_by = self._inventory_group_by()

        if not group_by:
            return self._format_inventory_table(
                chart_name, cluster_names, cluster_configs, columns)

        grouped = {}
        for cluster in cluster_names:
            group = self._cluster_group(cluster, cluster_configs.get(cluster))
            grouped.setdefault(group, []).append(cluster)

        group_order = self._inventory_group_order()
        ordered_groups = [g for g in group_order if g in grouped]
        for group in sorted(grouped.keys()):
            if group not in ordered_groups:
                ordered_groups.append(group)

        header_tpl = self._inventory_config().get('group_header_template', '### {group}')
        sections = []
        for group in ordered_groups:
            clusters = grouped.get(group)
            if not clusters:
                continue
            table = self._format_inventory_table(
                chart_name, clusters, cluster_configs, columns)
            sections.append(f"{header_tpl.format(group=group)}\n\n{table}")

        if not sections:
            return self._load_template('helm-deployment-inventory-empty.md').strip()
        return '\n\n'.join(sections)

    def _load_configs_marker_file(self, configs_root):
        """Load the configs marker YAML (e.g. chart registry)."""
        if not configs_root:
            return {}
        registry_path = os.path.join(configs_root, self._configs_marker())
        if not os.path.isfile(registry_path):
            return {}
        try:
            mtime = os.path.getmtime(registry_path)
        except OSError:
            return {}
        cache_key = registry_path
        cached = _CHART_REGISTRY_CACHE.get(cache_key)
        if cached and cached.get('mtime') == mtime:
            return cached['data']
        data = self._runner.load_yaml_file(registry_path) or {}
        _CHART_REGISTRY_CACHE[cache_key] = {'mtime': mtime, 'data': data}
        return data

    def _get_chart_registry_meta(self, registry, chart_name):
        """Resolve per-chart metadata under ``chart_registry_charts_path`` (default helm.charts)."""
        path = self._inventory_config().get(
            'chart_registry_charts_path', _DEFAULT_CHART_REGISTRY_CHARTS_PATH)
        node = registry
        for part in path.split('.'):
            if not isinstance(node, dict):
                return {}
            node = node.get(part)
        if not isinstance(node, dict):
            return {}
        meta = node.get(chart_name)
        return meta if isinstance(meta, dict) else {}

    @staticmethod
    def _derive_file_url(base_url, filename):
        """Build a file URL from a repo directory URL (tree → blob for GitHub)."""
        base = base_url.rstrip('/')
        if '/tree/' in base:
            base = base.replace('/tree/', '/blob/', 1)
        return f'{base}/{filename.lstrip("/")}'

    def _resolve_chart_link_url(self, chart_meta, spec):
        if spec.get('from_key') and spec.get('path_suffix'):
            base = chart_meta.get(spec['from_key'])
            if not base or not str(base).strip():
                return None
            return self._derive_file_url(str(base).strip(), spec['path_suffix'])
        key = spec.get('key')
        if not key:
            return None
        url = chart_meta.get(key)
        if not url or not str(url).strip():
            return None
        return str(url).strip()

    def _chart_link_text(self, chart_name, spec, url):
        if spec.get('link_text'):
            return spec['link_text'].replace('{chart}', chart_name)
        if spec.get('path_suffix'):
            return spec['path_suffix']
        basename = url.rstrip('/').split('/')[-1]
        if basename:
            return basename
        return chart_name

    def _format_chart_links_section(self, chart_name, configs_root):
        """Chart-level links from the configs marker file (URLs live in repo config)."""
        link_specs = self._chart_links_specs()
        if not link_specs:
            return ''
        registry = self._load_configs_marker_file(configs_root)
        chart_meta = self._get_chart_registry_meta(registry, chart_name)
        heading = self._inventory_config().get(
            'chart_links_heading', _DEFAULT_CHART_LINKS_HEADING)

        rows = []
        for spec in link_specs:
            url = self._resolve_chart_link_url(chart_meta, spec)
            if not url:
                continue
            label = spec.get('label') or spec.get('key') or spec.get('from_key')
            text = self._chart_link_text(chart_name, spec, url)
            cell = f'[{text}]({url})'
            note = spec.get('note')
            if note:
                cell = f'{cell} — {note}'
            rows.append(f'| {label} | {cell} |')

        if not rows:
            return ''
        table = '| Resource | Location |\n|----------|----------|\n' + '\n'.join(rows)
        return f'## {heading}\n\n{table}\n\n'

    def _write_chart_inventory_readme(self, chart_dir, chart_name, cluster_configs,
                            chart_tpl, chart_pipeline, configs_root=None):
        per_chart_dir = os.path.join(chart_dir, 'generated')
        cluster_names = self._list_generated_cluster_names(per_chart_dir)
        chart_content = chart_tpl.format(
            chart_name=chart_name,
            bridge_filename=self._runner.bridge_filename,
            overrides_subdir=self._runner.overrides_subdir,
            pipeline_diagram=chart_pipeline,
            override_files_list=self._format_override_files_list(
                self._list_chart_override_files(chart_dir)),
            chart_links_section=self._format_chart_links_section(chart_name, configs_root),
            deployment_inventory=self._format_deployment_inventory(
                chart_name, cluster_names, cluster_configs),
        )
        chart_readme = os.path.join(chart_dir, 'README.md')
        self._write_if_changed(chart_readme, chart_content)
        self.cleanup_legacy_readme(per_chart_dir)
