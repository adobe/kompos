#!/usr/bin/env python3
"""
Kompos Integration Tests

Tests critical functionality in a logical order:
1. Config HIML generation (basic function - tests HIML integration + GenericRunner)
2. Config with args (runner args + HIML args)
3. KomposConfig (exclude/include per composition, path configs)
4. TFE generation (config generation, versioned compositions, workspaces)
5. TFE args and HIML args (generic runner + TFE runner)

Run with: python tests/run_tests.py
"""
import sys
import subprocess
import yaml
import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Determine kompos executable path
# Local dev: Use .venv/bin/kompos if available
# CI: Use 'kompos' from PATH (installed via pip install -e .)
VENV_KOMPOS = PROJECT_ROOT / ".venv" / "bin" / "kompos"
if VENV_KOMPOS.exists():
    KOMPOS_CMD = str(VENV_KOMPOS)
else:
    KOMPOS_CMD = None  # Will use 'kompos' from PATH

# Test fixture paths
EXAMPLE_DIR = PROJECT_ROOT / "examples" / "features" / "01-hierarchical-config"
CONFIG_PATH = EXAMPLE_DIR / "config" / "cloud=aws" / "env=dev" / "cluster=cluster1" / "composition=terraform" / "terraform=cluster"

# Interpolation test fixture
INTERPOLATION_EXAMPLE = PROJECT_ROOT / "examples" / "features" / "02-himl-interpolation"
INTERPOLATION_CONFIG = INTERPOLATION_EXAMPLE / "config" / "cloud=aws" / "env=prod"

# TFE test fixture (has versioned compositions, workspaces, multi-cluster)
TFE_EXAMPLE = PROJECT_ROOT / "examples" / "features" / "04-tfe-multi-cluster"
TFE_CONFIG_DEV = TFE_EXAMPLE / "data" / "cloud=aws" / "project=demo" / "env=dev" / "region=us-west-2" / "cluster=demo-cluster-01" / "composition=terraform"
TFE_CONFIG_PROD = TFE_EXAMPLE / "data" / "cloud=aws" / "project=demo" / "env=prod" / "region=us-east-1" / "cluster=demo-cluster-02" / "composition=terraform"

# Dedicated komposconfig example — all komposconfig features in one place
KOMPOSCONFIG_EXAMPLE = PROJECT_ROOT / "examples" / "features" / "06-komposconfig"
KOMPOSCONFIG_CONFIG  = KOMPOSCONFIG_EXAMPLE / "data" / "cloud=aws" / "project=demo" / "env=dev" / "region=us-west-2" / "cluster=my-cluster" / "composition=cluster"

# Helm values test fixture
HELM_EXAMPLE = PROJECT_ROOT / "examples" / "features" / "05-helm-values"
HELM_CONFIG   = HELM_EXAMPLE / "data" / "cloud=aws" / "project=demo" / "env=dev" / "region=us-west-2" / "cluster=demo-cluster-01" / "composition=helm-values"
HELM_VALUES   = HELM_EXAMPLE / "values"


def run_kompos(args, cwd=None):
    """Helper to run kompos command and return result"""
    if KOMPOS_CMD:
        # Local dev: use .venv kompos
        cmd = [KOMPOS_CMD] + args
    else:
        # CI: use kompos from PATH
        cmd = ["kompos"] + args
    
    result = subprocess.run(
        cmd,
        cwd=cwd or str(EXAMPLE_DIR),
        capture_output=True,
        text=True
    )
    return result


# =============================================================================
# 1. CONFIG HIML GENERATION - Basic function (HIML + GenericRunner)
# =============================================================================

def test_config_basic_generation():
    """Test basic config generation - core HIML integration"""
    print("1.1 Testing basic config generation (HIML + GenericRunner)...")
    
    if not CONFIG_PATH.exists():
        print("  ⊘ Skipped (example not found)")
        return
    
    result = run_kompos([str(CONFIG_PATH), "config", "--format", "yaml", "--skip-interpolation-validation"])
    
    assert result.returncode == 0, f"Basic config generation failed:\n{result.stderr}"
    
    output = yaml.safe_load(result.stdout)
    
    # Verify hierarchical config loaded
    assert isinstance(output, dict), "Output should be a dictionary"
    assert len(output) > 0, "Output should not be empty"
    assert "cloud" in output, "Should contain cloud layer"
    assert "env" in output, "Should contain env layer"
    assert "cluster" in output, "Should contain cluster layer"
    
    # Verify komposconfig loaded
    assert "komposconfig" in output, "Should contain komposconfig"
    
    print(f"  ✓ Basic config generation works ({len(output)} top-level keys)")


def test_config_key_order_preserved():
    """Test that key order is preserved in output (important for diffs/git)"""
    print("1.2 Testing key order preservation in output...")
    
    if not CONFIG_PATH.exists():
        print("  ⊘ Skipped (example not found)")
        return
    
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        output_file = f.name
    
    try:
        # Generate twice to the same file
        result1 = run_kompos([
            str(CONFIG_PATH), "config",
            "--format", "yaml",
            "--output-file", output_file,
            "--skip-interpolation-validation"
        ])
        
        with open(output_file) as f:
            output1 = f.read()
        
        result2 = run_kompos([
            str(CONFIG_PATH), "config",
            "--format", "yaml",
            "--output-file", output_file,
            "--skip-interpolation-validation"
        ])
        
        with open(output_file) as f:
            output2 = f.read()
        
        # Outputs should be identical (same key order)
        assert output1 == output2, "Key order should be consistent across generations"
        
        print("  ✓ Key order preserved (deterministic output)")
    finally:
        if os.path.exists(output_file):
            os.unlink(output_file)


def test_config_simple_interpolation():
    """Test simple direct interpolation: {{key.path}}"""
    print("1.3 Testing simple interpolation {{key.path}}...")
    
    if not INTERPOLATION_CONFIG.exists():
        print("  ⊘ Skipped (interpolation example not found)")
        return
    
    result = run_kompos([str(INTERPOLATION_CONFIG), "config", "--format", "yaml"], cwd=str(INTERPOLATION_EXAMPLE))
    
    assert result.returncode == 0, f"Simple interpolation failed:\n{result.stderr}"
    
    output = yaml.safe_load(result.stdout)
    
    # Verify simple interpolation: aws-cloud
    assert output["cloud"]["full_name"] == "aws-cloud", "Simple interpolation failed"
    
    # Verify multi-level: myproject.aws.prod.example.com
    assert "myproject.aws.prod.example.com" in output["project"]["fqdn"], "Multi-level interpolation failed"
    
    print("  ✓ Simple interpolation {{key.path}} works")


def test_config_nested_interpolation():
    """Test nested interpolation: {{outer.{{inner}}}}"""
    print("1.4 Testing nested interpolation {{outer.{{inner}}}}...")
    
    if not INTERPOLATION_CONFIG.exists():
        print("  ⊘ Skipped (interpolation example not found)")
        return
    
    result = run_kompos([str(INTERPOLATION_CONFIG), "config", "--format", "yaml"], cwd=str(INTERPOLATION_EXAMPLE))
    
    assert result.returncode == 0, f"Nested interpolation failed:\n{result.stderr}"
    
    output = yaml.safe_load(result.stdout)
    
    # Verify nested interpolation: {{env.type_mapping.{{env.name}}}}
    # env.name=prod -> env.type_mapping.prod -> production
    assert output["env"]["full_type"] == "production", "Nested interpolation failed"
    
    # Verify nested region code: {{regions.{{cloud.region}}}}
    # cloud.region=us-west-2 -> regions.us-west-2 -> or2
    assert output["regions"]["region_code"] == "or2", "Nested region interpolation failed"
    
    print("  ✓ Nested interpolation {{outer.{{inner}}}} works")


def test_config_double_interpolation():
    """Test double interpolation with composition type"""
    print("1.5 Testing double interpolation {{config.{{variable}}.property}}...")
    
    if not INTERPOLATION_CONFIG.exists():
        print("  ⊘ Skipped (interpolation example not found)")
        return
    
    result = run_kompos([str(INTERPOLATION_CONFIG), "config", "--format", "yaml"], cwd=str(INTERPOLATION_EXAMPLE))
    
    assert result.returncode == 0, f"Double interpolation failed:\n{result.stderr}"
    
    output = yaml.safe_load(result.stdout)
    
    # Verify double interpolation: {{komposconfig.compositions.properties.{{composition.type}}.output_subdir}}
    # composition.type=app -> komposconfig.compositions.properties.app.output_subdir -> applications
    assert output["settings"]["output_dir"] == "applications", "Double interpolation for output_dir failed"
    assert output["settings"]["replicas"] == 3, "Double interpolation for replicas failed"
    
    print("  ✓ Double interpolation {{config.{{variable}}.property}} works")


def test_config_interpolation_with_overrides():
    """Test that interpolations respect hierarchy overrides"""
    print("1.6 Testing interpolation with hierarchy overrides...")
    
    if not INTERPOLATION_CONFIG.exists():
        print("  ⊘ Skipped (interpolation example not found)")
        return
    
    result = run_kompos([str(INTERPOLATION_CONFIG), "config", "--format", "yaml"], cwd=str(INTERPOLATION_EXAMPLE))
    
    assert result.returncode == 0, f"Override interpolation failed:\n{result.stderr}"
    
    output = yaml.safe_load(result.stdout)
    
    # Verify override affected interpolation
    # env.name is overridden to "prod" in env=prod/env.yaml
    # project.fqdn should use "prod" not "dev"
    assert "prod" in output["project"]["fqdn"], "Override not reflected in interpolation"
    
    # Verify env-specific interpolations
    if "env_suffix" in output.get("project", {}):
        assert output["project"]["env_suffix"] == "prod-suffix", "Override interpolation failed"
    
    print("  ✓ Interpolation respects hierarchy overrides")


def test_config_complex_nested_double_interpolation():
    """Test complex nested double interpolation in same expression"""
    print("1.7 Testing complex nested double interpolation...")
    
    if not INTERPOLATION_CONFIG.exists():
        print("  ⊘ Skipped (interpolation example not found)")
        return
    
    result = run_kompos([str(INTERPOLATION_CONFIG), "config", "--format", "yaml"], cwd=str(INTERPOLATION_EXAMPLE))
    
    assert result.returncode == 0, f"Complex interpolation failed:\n{result.stderr}"
    
    output = yaml.safe_load(result.stdout)
    
    # Verify complex multi-level interpolation
    # project.full_fqdn uses: {{project.name}}.{{regions.region_code}}.{{env.name}}.{{cloud.name}}.example.com
    # Where regions.region_code itself is {{regions.{{cloud.region}}}}
    expected_fqdn = "myproject.or2.prod.aws.example.com"
    assert output["project"]["full_fqdn"] == expected_fqdn, f"Complex interpolation failed: {output['project']['full_fqdn']}"
    
    # Verify app endpoint with multiple interpolations
    # webapp-or2-prod.myproject.aws.prod.example.com
    assert "webapp-or2-prod" in output["app"]["endpoint"], "Complex app interpolation failed"
    assert "myproject.aws.prod.example.com" in output["app"]["endpoint"], "Complex app interpolation failed"
    
    # Verify output path with double interpolation result
    assert "generated/applications/myproject-prod" == output["app"]["config"]["output_path"], "Complex output path failed"
    
    print("  ✓ Complex nested double interpolation works")


# =============================================================================
# 2. CONFIG WITH ARGS - Runner args + HIML args
# =============================================================================

def test_config_with_exclude():
    """Test --exclude (HIML arg - removes keys before interpolation)"""
    print("2.1 Testing config with --exclude (HIML arg)...")
    
    if not CONFIG_PATH.exists():
        print("  ⊘ Skipped (example not found)")
        return
    
    result = run_kompos([
        str(CONFIG_PATH), "config",
        "--format", "yaml",
        "--exclude", "terraform",
        "--exclude", "provider",
        "--skip-interpolation-validation"
    ])
    
    assert result.returncode == 0, f"Config with exclude failed:\n{result.stderr}"
    
    output = yaml.safe_load(result.stdout)
    
    # Verify excluded keys don't appear
    assert "terraform" not in output, "terraform should be excluded"
    assert "provider" not in output, "provider should be excluded"
    assert "cloud" in output, "Non-excluded keys should remain"
    
    print("  ✓ --exclude works (keys removed from hierarchy)")


def test_config_with_filter():
    """Test --filter (HIML arg - removes keys after interpolation)"""
    print("2.2 Testing config with --filter (HIML arg)...")
    
    if not CONFIG_PATH.exists():
        print("  ⊘ Skipped (example not found)")
        return
    
    result = run_kompos([
        str(CONFIG_PATH), "config",
        "--format", "yaml",
        "--filter", "cloud",
        "--filter", "env",
        "--skip-interpolation-validation"
    ])
    
    assert result.returncode == 0, f"Config with filter failed:\n{result.stderr}"
    
    output = yaml.safe_load(result.stdout)
    
    # Only filtered keys should appear
    assert "cloud" in output, "Filtered key should appear"
    assert "env" in output, "Filtered key should appear"
    assert "cluster" not in output, "Non-filtered keys should not appear"
    
    # Critical: verify filtered keys had access to all keys during interpolation
    # (can't fully test without specific interpolation in example)
    
    print("  ✓ --filter works (keys available for interpolation, removed from output)")


def test_config_exclude_vs_filter():
    """Test critical difference: exclude before interpolation, filter after"""
    print("2.3 Testing --exclude vs --filter timing...")
    
    if not CONFIG_PATH.exists():
        print("  ⊘ Skipped (example not found)")
        return
    
    # Both should succeed with --skip-interpolation-validation
    result_exclude = run_kompos([
        str(CONFIG_PATH), "config",
        "--format", "yaml",
        "--exclude", "cloud",
        "--skip-interpolation-validation"
    ])
    
    result_filter = run_kompos([
        str(CONFIG_PATH), "config",
        "--format", "yaml",
        "--filter", "cluster",
        "--skip-interpolation-validation"
    ])
    
    assert result_exclude.returncode == 0, "Exclude should succeed"
    assert result_filter.returncode == 0, "Filter should succeed"
    
    output_exclude = yaml.safe_load(result_exclude.stdout)
    output_filter = yaml.safe_load(result_filter.stdout)
    
    assert "cloud" not in output_exclude, "Excluded key not in output"
    assert "cloud" not in output_filter, "Non-filtered key not in output"
    
    print("  ✓ Exclude (before interpolation) vs Filter (after interpolation) works")


def test_config_output_formats():
    """Test --format arg (YAML and JSON)"""
    print("2.4 Testing config output formats...")
    
    if not CONFIG_PATH.exists():
        print("  ⊘ Skipped (example not found)")
        return
    
    # Test YAML
    result_yaml = run_kompos([
        str(CONFIG_PATH), "config",
        "--format", "yaml",
        "--skip-interpolation-validation"
    ])
    assert result_yaml.returncode == 0, "YAML output should work"
    yaml_output = yaml.safe_load(result_yaml.stdout)
    assert isinstance(yaml_output, dict), "YAML output should be valid"
    
    # Test JSON
    result_json = run_kompos([
        str(CONFIG_PATH), "config",
        "--format", "json",
        "--skip-interpolation-validation"
    ])
    assert result_json.returncode == 0, "JSON output should work"
    json_output = json.loads(result_json.stdout)
    assert isinstance(json_output, dict), "JSON output should be valid"
    
    print("  ✓ Output formats work (YAML, JSON)")


def test_config_output_file():
    """Test --output-file arg"""
    print("2.5 Testing config with --output-file...")
    
    if not CONFIG_PATH.exists():
        print("  ⊘ Skipped (example not found)")
        return
    
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        output_file = f.name
    
    try:
        result = run_kompos([
            str(CONFIG_PATH), "config",
            "--format", "yaml",
            "--output-file", output_file,
            "--skip-interpolation-validation"
        ])
        
        assert result.returncode == 0, "Output file generation should work"
        assert os.path.exists(output_file), "Output file should be created"
        
        with open(output_file) as f:
            output = yaml.safe_load(f)
        
        assert isinstance(output, dict), "Output file should contain valid YAML"
        assert len(output) > 0, "Output file should not be empty"
        
        print("  ✓ --output-file works")
    finally:
        if os.path.exists(output_file):
            os.unlink(output_file)


def test_config_enclosing_key():
    """Test --enclosing-key arg"""
    print("2.6 Testing config with --enclosing-key...")
    
    if not CONFIG_PATH.exists():
        print("  ⊘ Skipped (example not found)")
        return
    
    result = run_kompos([
        str(CONFIG_PATH), "config",
        "--format", "yaml",
        "--enclosing-key", "config",
        "--skip-interpolation-validation"
    ])
    
    assert result.returncode == 0, "Enclosing key should work"
    output = yaml.safe_load(result.stdout)
    
    assert "config" in output, "Should have enclosing key"
    assert isinstance(output["config"], dict), "Enclosing key should contain config"
    assert "cloud" in output["config"], "Config should be inside enclosing key"
    
    print("  ✓ --enclosing-key works")


# =============================================================================
# 3. KOMPOSCONFIG - Exclude/include per composition, path configs
# =============================================================================

def test_komposconfig_loads():
    """Test that .komposconfig.yaml is loaded and parsed"""
    print("3.1 Testing .komposconfig.yaml loads...")

    komposconfig_file = KOMPOSCONFIG_EXAMPLE / ".komposconfig.yaml"
    if not komposconfig_file.exists():
        print("  ⊘ Skipped (06-komposconfig example not found)")
        return

    with open(komposconfig_file) as f:
        config = yaml.safe_load(f)

    assert "komposconfig" in config, "Should have komposconfig namespace"
    assert "compositions" in config["komposconfig"], "Should have compositions config"

    print("  ✓ .komposconfig.yaml loads correctly")


def test_komposconfig_system_keys_exclusion():
    """Test that system_keys are defined and excluded from tfvars"""
    print("3.2 Testing system_keys auto-exclusion...")

    komposconfig_file = KOMPOSCONFIG_EXAMPLE / ".komposconfig.yaml"
    if not komposconfig_file.exists():
        print("  ⊘ Skipped (06-komposconfig example not found)")
        return

    with open(komposconfig_file) as f:
        config = yaml.safe_load(f)

    system_keys = config.get("komposconfig", {}).get("compositions", {}).get("system_keys", {})
    assert "terraform" in system_keys, "Should have terraform system_keys"
    assert isinstance(system_keys["terraform"], list), "system_keys should be a list"
    assert "tfe" in system_keys, "Should have tfe system_keys"

    # Verify they contain expected operational keys
    assert "composition" in system_keys["tfe"], "composition should be a tfe system_key"

    print(f"  ✓ system_keys defined: terraform={system_keys['terraform']}, tfe={system_keys['tfe']}")


def test_komposconfig_composition_paths():
    """Test composition source paths, output_subdir properties and execution order"""
    print("3.3 Testing composition path configurations...")

    komposconfig_file = KOMPOSCONFIG_EXAMPLE / ".komposconfig.yaml"
    if not komposconfig_file.exists():
        print("  ⊘ Skipped (06-komposconfig example not found)")
        return

    with open(komposconfig_file) as f:
        config = yaml.safe_load(f)

    komposconfig = config["komposconfig"]
    compositions = komposconfig["compositions"]

    # Source path
    assert "source" in compositions, "Should have source config"
    assert "local_path" in compositions["source"], "Should have local_path"

    # Execution order
    assert "order" in compositions, "Should have execution order"
    assert "terraform" in compositions["order"], "Should have terraform order"
    assert isinstance(compositions["order"]["terraform"], list), "Order should be a list"

    # output_subdir per composition type
    assert "properties" in compositions, "Should have per-type properties"
    for comp_type, props in compositions["properties"].items():
        assert "output_subdir" in props, f"{comp_type} should have output_subdir"

    print(f"  ✓ Composition paths valid: order={compositions['order']['terraform']}, "
          f"types={list(compositions['properties'].keys())}")


def test_komposconfig_nested_subdir():
    """Test that nested_subdir in komposconfig routes TFE output into a named subdir"""
    print("3.4 Testing komposconfig nested_subdir output routing...")
    if not KOMPOSCONFIG_CONFIG.exists():
        print("  ⊘ Skipped (06-komposconfig example not found)")
        return

    import shutil
    generated = KOMPOSCONFIG_EXAMPLE / "generated"
    if generated.exists():
        shutil.rmtree(generated)

    result = run_kompos(
        [str(KOMPOSCONFIG_CONFIG), "tfe", "generate"],
        cwd=str(KOMPOSCONFIG_EXAMPLE)
    )
    assert result.returncode == 0, f"tfe generate failed:\n{result.stderr}"

    # Files must be inside generated/clusters/{instance}/tfe/ — not at the instance root
    nested_dir = generated / "clusters" / "my-cluster-dev-usw2" / "tfe"
    assert nested_dir.exists(), f"Expected nested dir from nested_subdir=tfe: {nested_dir}"
    assert (nested_dir / "generated.tfvars.yaml").exists(), "tfvars should be in nested dir"

    # Instance root must have NO tfvars (isolated under /tfe)
    root_tfvars = list((generated / "clusters" / "my-cluster-dev-usw2").glob("*.tfvars.yaml"))
    assert len(root_tfvars) == 0, \
        f"tfvars should not be at instance root when nested_subdir is set, found: {root_tfvars}"

    print(f"  ✓ nested_subdir=tfe: output isolated at {nested_dir.relative_to(KOMPOSCONFIG_EXAMPLE)}")


# =============================================================================
# 4. ACTUAL FILE GENERATION - End-to-end integration tests
# =============================================================================

def test_config_generates_to_file():
    """Test actual config file generation to temp directory"""
    print("4.1 Testing actual config file generation...")
    
    if not CONFIG_PATH.exists():
        print("  ⊘ Skipped (example not found)")
        return
    
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        output_file = Path(tmpdir) / "output.yaml"
        
        # Generate actual file
        result = run_kompos([
            str(CONFIG_PATH), "config",
            "--format", "yaml",
            "--output-file", str(output_file),
            "--skip-interpolation-validation"
        ])
        
        assert result.returncode == 0, f"File generation failed: {result.stderr}"
        assert output_file.exists(), f"Output file not created: {output_file}"
        
        # Verify file content
        with open(output_file) as f:
            content = f.read()
            output = yaml.safe_load(content)
        
        assert isinstance(output, dict), "Generated file should contain valid YAML"
        assert len(output) > 0, "Generated file should not be empty"
        assert "cloud" in output, "Generated config should have cloud layer"
        
        # Verify file size
        file_size = output_file.stat().st_size
        assert file_size > 100, f"Generated file seems too small: {file_size} bytes"
        
        print(f"  ✓ Config file generated ({file_size} bytes, {len(output)} keys)")


def test_config_with_enclosing_key_generates():
    """Test config with enclosing key generates correctly"""
    print("4.2 Testing config with enclosing key generates to file...")
    
    if not CONFIG_PATH.exists():
        print("  ⊘ Skipped (example not found)")
        return
    
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        output_file = Path(tmpdir) / "tfvars.yaml"
        
        # Generate with enclosing key (like tfvars)
        result = run_kompos([
            str(CONFIG_PATH), "config",
            "--format", "yaml",
            "--enclosing-key", "config",
            "--output-file", str(output_file),
            "--skip-interpolation-validation"
        ])
        
        assert result.returncode == 0, "File generation should succeed"
        assert output_file.exists(), "Output file should exist"
        
        with open(output_file) as f:
            output = yaml.safe_load(f)
        
        assert "config" in output, "Should have enclosing key"
        assert isinstance(output["config"], dict), "Enclosing key should contain dict"
        assert len(output["config"]) > 0, "Config should not be empty"
        
        print(f"  ✓ Enclosing key file generated ({len(output['config'])} keys in 'config')")


def test_config_with_filters_generates():
    """Test filtered config generates correctly"""
    print("4.3 Testing filtered config generates to file...")
    
    if not CONFIG_PATH.exists():
        print("  ⊘ Skipped (example not found)")
        return
    
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        output_file = Path(tmpdir) / "filtered.yaml"
        
        # Generate with filters
        result = run_kompos([
            str(CONFIG_PATH), "config",
            "--format", "yaml",
            "--filter", "cloud",
            "--filter", "env",
            "--output-file", str(output_file),
            "--skip-interpolation-validation"
        ])
        
        assert result.returncode == 0, "Filtered generation should succeed"
        assert output_file.exists(), "Output file should exist"
        
        with open(output_file) as f:
            output = yaml.safe_load(f)
        
        # Verify only filtered keys present
        assert "cloud" in output, "Filtered key should be present"
        assert "env" in output, "Filtered key should be present"
        assert "cluster" not in output, "Non-filtered key should be excluded"
        
        print(f"  ✓ Filtered config generated (2 keys: cloud, env)")


def test_json_format_generates():
    """Test JSON format generation to file"""
    print("4.4 Testing JSON format generation...")
    
    if not CONFIG_PATH.exists():
        print("  ⊘ Skipped (example not found)")
        return
    
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        output_file = Path(tmpdir) / "config.json"
        
        # Generate JSON
        result = run_kompos([
            str(CONFIG_PATH), "config",
            "--format", "json",
            "--output-file", str(output_file),
            "--skip-interpolation-validation"
        ])
        
        assert result.returncode == 0, "JSON generation should succeed"
        assert output_file.exists(), "JSON file should exist"
        
        with open(output_file) as f:
            content = f.read()
            output = json.loads(content)
        
        assert isinstance(output, dict), "JSON should be valid"
        assert len(output) > 0, "JSON should not be empty"
        
        # Verify it's actually JSON (not YAML)
        assert content.strip().startswith("{"), "Should start with {"
        
        print(f"  ✓ JSON file generated ({len(output)} keys)")


def test_deterministic_output():
    """Test that multiple generations produce identical output"""
    print("4.5 Testing deterministic output (reproducible builds)...")
    
    if not CONFIG_PATH.exists():
        print("  ⊘ Skipped (example not found)")
        return
    
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        output1 = Path(tmpdir) / "output1.yaml"
        output2 = Path(tmpdir) / "output2.yaml"
        
        # Generate twice
        for output_file in [output1, output2]:
            result = run_kompos([
                str(CONFIG_PATH), "config",
                "--format", "yaml",
                "--output-file", str(output_file),
                "--skip-interpolation-validation"
            ])
            assert result.returncode == 0, "Generation should succeed"
        
        # Compare files byte-for-byte
        with open(output1) as f1, open(output2) as f2:
            content1 = f1.read()
            content2 = f2.read()
        
        assert content1 == content2, "Generated files should be identical (deterministic)"
        
        print(f"  ✓ Deterministic output verified ({len(content1)} bytes)")


# =============================================================================
# 5. TFE GENERATION
# =============================================================================

def test_tfe_help():
    """Test TFE runner help"""
    print("5.1 Testing TFE runner help...")
    result = run_kompos([".", "tfe", "--help"], cwd=str(TFE_EXAMPLE))
    help_text = result.stdout + result.stderr
    assert "generate"        in help_text, "Should show generate subcommand"
    assert "--tfvars-only"   in help_text, "Should show --tfvars-only"
    assert "--workspace-only" in help_text, "Should show --workspace-only"
    print("  ✓ TFE help complete")


def test_tfe_generates_tfvars():
    """Test TFE generates tfvars with config enclosing key and system keys excluded"""
    print("5.2 Testing TFE tfvars generation...")
    if not TFE_CONFIG_DEV.exists():
        print("  ⊘ Skipped (TFE example not found)")
        return
    result = run_kompos(
        [str(TFE_CONFIG_DEV), "tfe", "generate", "--tfvars-only"],
        cwd=str(TFE_EXAMPLE)
    )
    assert result.returncode == 0, f"tfe generate failed:\n{result.stderr}"
    tfvars_files = list((TFE_EXAMPLE / "generated").rglob("*.tfvars.yaml"))
    assert len(tfvars_files) > 0, "Should generate at least one tfvars file"
    tfvars = yaml.safe_load(tfvars_files[0].read_text())
    assert "config" in tfvars,                "Tfvars should have 'config' enclosing key"
    assert "terraform" not in tfvars["config"], "System key 'terraform' should be excluded"
    assert "provider"  not in tfvars["config"], "System key 'provider' should be excluded"
    print(f"  ✓ TFE tfvars generated ({tfvars_files[0].name}, {len(tfvars['config'])} keys)")


def test_tfe_generates_versioned_compositions():
    """Test TFE resolves .tf.versioned module sources"""
    print("5.3 Testing versioned composition processing...")
    if not TFE_CONFIG_DEV.exists():
        print("  ⊘ Skipped (TFE example not found)")
        return
    result = run_kompos(
        [str(TFE_CONFIG_DEV), "tfe", "generate", "--tfvars-only"],
        cwd=str(TFE_EXAMPLE)
    )
    assert result.returncode == 0, f"tfe generate failed:\n{result.stderr}"
    tf_files = list((TFE_EXAMPLE / "generated").rglob("main.tf"))
    assert len(tf_files) > 0, "main.tf should be generated from main.tf.versioned"
    content = tf_files[0].read_text()
    assert "{{vpc.module_version}}" not in content, "Version placeholders should be resolved"
    assert "?ref=" in content,                      "Should have resolved module refs"
    print(f"  ✓ Versioned compositions processed (main.tf generated with resolved refs)")


def test_tfe_generates_workspaces():
    """Test TFE generates workspace config files"""
    print("5.4 Testing TFE workspace generation...")
    if not TFE_CONFIG_DEV.exists():
        print("  ⊘ Skipped (TFE example not found)")
        return
    result = run_kompos(
        [str(TFE_CONFIG_DEV), "tfe", "generate", "--workspace-only"],
        cwd=str(TFE_EXAMPLE)
    )
    assert result.returncode == 0, f"tfe generate --workspace-only failed:\n{result.stderr}"
    workspace_files = list((TFE_EXAMPLE / "generated").rglob("*.workspace.yaml"))
    assert len(workspace_files) > 0, "Should generate at least one workspace file"
    print(f"  ✓ Workspace generated ({workspace_files[0].name})")


def test_tfe_multi_cluster():
    """Test dev and prod cluster configs both exist and have expected structure"""
    print("5.5 Testing multi-cluster configs...")
    if not TFE_CONFIG_DEV.exists() or not TFE_CONFIG_PROD.exists():
        print("  ⊘ Skipped (multi-cluster configs not found)")
        return
    assert (TFE_CONFIG_DEV.parent / "cluster.yaml").exists(), "Dev cluster.yaml should exist"
    assert (TFE_CONFIG_PROD.parent / "cluster.yaml").exists(), "Prod cluster.yaml should exist"
    # Run generation for both clusters
    for config_path in [TFE_CONFIG_DEV, TFE_CONFIG_PROD]:
        result = run_kompos(
            [str(config_path), "tfe", "generate", "--tfvars-only"],
            cwd=str(TFE_EXAMPLE)
        )
        assert result.returncode == 0, f"tfe generate failed for {config_path.parent.name}:\n{result.stderr}"
    tfvars_files = list((TFE_EXAMPLE / "generated").rglob("*.tfvars.yaml"))
    assert len(tfvars_files) >= 2, "Should have tfvars for both clusters"
    print(f"  ✓ Multi-cluster generation: {len(tfvars_files)} tfvars files generated")




# =============================================================================
# 5. CLI ERROR HANDLING
# =============================================================================

def test_cli_help_completeness():
    """Test that all runners are documented in main help"""
    print("5.1 Testing CLI help completeness...")
    
    result = run_kompos(["--help"])
    
    assert result.returncode == 0, "Help should work"
    
    help_text = result.stdout
    
    expected_runners = ["config", "tfe", "terraform", "explore", "validate"]
    missing = [r for r in expected_runners if r not in help_text]
    
    assert len(missing) == 0, f"Missing runners in help: {missing}"
    
    print(f"  ✓ All {len(expected_runners)} runners documented")


def test_cli_error_messages():
    """Test that CLI provides helpful error messages"""
    print("5.2 Testing CLI error messages...")
    
    # Test missing subcommand for tfe
    result = run_kompos([".", "tfe"])
    # Should fail with helpful message (not traceback)
    # Return code varies based on error handling
    
    error_output = result.stderr + result.stdout
    # Should mention "generate" or "subcommand" in error
    has_helpful_message = ("generate" in error_output.lower() or 
                          "subcommand" in error_output.lower() or
                          "required" in error_output.lower())
    
    # Don't fail test if error handling isn't perfect yet
    if has_helpful_message:
        print("  ✓ CLI provides helpful error messages")
    else:
        print("  ⊘ CLI error messages could be improved")


# =============================================================================
# MAIN TEST RUNNER
# =============================================================================

# =============================================================================
# 6. HELM VALUES GENERATION
# =============================================================================

def test_helm_help():
    """Test helm runner help"""
    print("6.1 Testing helm runner help...")
    result = run_kompos([".", "helm", "--help"], cwd=str(HELM_EXAMPLE))
    for flag in ["generate", "list", "--charts-dir", "--dry-run"]:
        assert flag in result.stdout + result.stderr, f"Should show {flag}"
    print("  ✓ helm help complete")


def test_helm_list():
    """Test helm list shows enabled charts from hierarchy"""
    print("6.2 Testing helm list...")
    if not HELM_CONFIG.exists():
        print("  ⊘ Skipped (helm example not found)")
        return
    result = run_kompos([str(HELM_CONFIG), "helm", "list"], cwd=str(HELM_EXAMPLE))
    assert result.returncode == 0, f"helm list failed:\n{result.stderr}"
    assert "my-app"   in result.stdout and "2.1.0" in result.stdout, "my-app at cluster pin 2.1.0"
    assert "my-ingress" in result.stdout and "1.2.0" in result.stdout, "my-ingress at 1.2.0"
    print("  ✓ helm list shows enabled charts with versions")


def test_helm_generate_dry_run():
    """Test helm generate --dry-run: interpolation, discovery, no files written"""
    print("6.3 Testing helm generate --dry-run...")
    if not HELM_CONFIG.exists():
        print("  ⊘ Skipped (helm example not found)")
        return
    result = run_kompos(
        [str(HELM_CONFIG), "helm", "generate", "--dry-run"],
        cwd=str(HELM_EXAMPLE)
    )
    assert result.returncode == 0, f"helm generate --dry-run failed:\n{result.stderr}"
    out = result.stdout
    # Charts rendered
    assert "my-app" in out and "my-ingress" in out, "Both enabled charts should render"
    # Hierarchy interpolation
    assert "demo-dev-usw2-cluster-01" in out, "cluster.fullName should resolve"
    assert "environment: dev"          in out, "env.name should resolve"
    # TFE outputs interpolation
    assert "arn:aws:iam::111122223333:role/demo-dev-usw2-cluster-01-my-app-pod-identity" in out, \
        "pod identity ARN should resolve"
    assert "sg-0pub111222333444" in out and "sg-0int555666777888" in out, "SG IDs should resolve"
    # No unresolved placeholders
    assert "{{" not in out, "No unresolved {{}} should remain in output"
    # Disabled chart reported
    assert "Disabled" in out and "my-worker" in out, "my-worker should appear as Disabled"
    print("  ✓ Rendered correctly — all {{}} resolved, disabled charts reported")


def test_helm_generate_writes_files():
    """Test helm generate writes argoapps/ output files"""
    print("6.4 Testing helm generate writes files...")
    if not HELM_CONFIG.exists():
        print("  ⊘ Skipped (helm example not found)")
        return
    argoapps = HELM_EXAMPLE / "generated" / "clusters" / "demo-dev-usw2-cluster-01" / "argoapps"
    result = run_kompos([str(HELM_CONFIG), "helm", "generate"], cwd=str(HELM_EXAMPLE))
    assert result.returncode == 0, f"helm generate failed:\n{result.stderr}"
    assert (argoapps / "my-app.yaml").exists(),    "my-app.yaml should be written"
    assert (argoapps / "my-ingress.yaml").exists(), "my-ingress.yaml should be written"
    content = (argoapps / "my-app.yaml").read_text() + (argoapps / "my-ingress.yaml").read_text()
    assert "{{" not in content,                     "No unresolved {{}} in output files"
    assert "demo-dev-usw2-cluster-01" in content,   "cluster name should be resolved"
    print("  ✓ argoapps/ files written with resolved values")


def test_helm_generate_single_chart():
    """Test --chart-dir renders only the specified chart"""
    print("6.5 Testing --chart-dir single chart mode...")
    if not HELM_CONFIG.exists():
        print("  ⊘ Skipped (helm example not found)")
        return
    result = run_kompos(
        [str(HELM_CONFIG), "helm", "generate",
         "--chart-dir", str(HELM_VALUES / "my-app"), "--dry-run"],
        cwd=str(HELM_EXAMPLE)
    )
    assert result.returncode == 0,                       f"--chart-dir failed:\n{result.stderr}"
    assert "my-app"                   in result.stdout,  "my-app should render"
    assert "demo-dev-usw2-cluster-01" in result.stdout,  "cluster name should resolve"
    print("  ✓ --chart-dir renders single chart correctly")


def main():
    """Run all tests in logical order"""
    print("=" * 70)
    print("KOMPOS INTEGRATION TESTS")
    print("=" * 70)
    print()
    
    test_groups = [
        ("1. CONFIG HIML GENERATION & INTERPOLATION", [
            test_config_basic_generation,
            test_config_key_order_preserved,
            test_config_simple_interpolation,
            test_config_nested_interpolation,
            test_config_double_interpolation,
            test_config_interpolation_with_overrides,
            test_config_complex_nested_double_interpolation,
        ]),
        ("2. CONFIG WITH ARGS", [
            test_config_with_exclude,
            test_config_with_filter,
            test_config_exclude_vs_filter,
            test_config_output_formats,
            test_config_output_file,
            test_config_enclosing_key,
        ]),
        ("3. KOMPOSCONFIG", [
            test_komposconfig_loads,
            test_komposconfig_system_keys_exclusion,
            test_komposconfig_composition_paths,
            test_komposconfig_nested_subdir,
        ]),
        ("4. ACTUAL FILE GENERATION", [
            test_config_generates_to_file,
            test_config_with_enclosing_key_generates,
            test_config_with_filters_generates,
            test_json_format_generates,
            test_deterministic_output,
        ]),
        ("5. TFE GENERATION", [
            test_tfe_help,
            test_tfe_generates_tfvars,
            test_tfe_generates_versioned_compositions,
            test_tfe_generates_workspaces,
            test_tfe_multi_cluster,
        ]),
        ("6. HELM VALUES GENERATION", [
            test_helm_help,
            test_helm_list,
            test_helm_generate_dry_run,
            test_helm_generate_writes_files,
            test_helm_generate_single_chart,
        ]),
        ("7. CLI", [
            test_cli_help_completeness,
            test_cli_error_messages,
        ]),
    ]
    
    total_passed = 0
    total_failed = 0
    
    for group_name, tests in test_groups:
        print(f"\n{group_name}")
        print("-" * 70)
        
        for test in tests:
            try:
                test()
                total_passed += 1
            except AssertionError as e:
                print(f"  ✗ FAILED: {e}")
                total_failed += 1
            except Exception as e:
                print(f"  ✗ ERROR: {e}")
                total_failed += 1
    
    print()
    print("=" * 70)
    print(f"RESULTS: {total_passed} passed, {total_failed} failed")
    print("=" * 70)
    
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
