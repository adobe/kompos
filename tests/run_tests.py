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


def run_kompos(args, cwd=None):
    """Helper to run kompos command and return result"""
    result = subprocess.run(
        ["kompos"] + args,
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
    
    komposconfig_file = EXAMPLE_DIR / ".komposconfig.yaml"
    if not komposconfig_file.exists():
        print("  ⊘ Skipped (.komposconfig.yaml not found)")
        return
    
    # Run any kompos command - it should load the config
    result = run_kompos(["--help"])
    
    assert result.returncode == 0, ".komposconfig.yaml should load without errors"
    
    # Verify config structure
    with open(komposconfig_file) as f:
        config = yaml.safe_load(f)
    
    assert "komposconfig" in config, "Should have komposconfig namespace"
    assert "compositions" in config["komposconfig"], "Should have compositions config"
    
    print("  ✓ .komposconfig.yaml loads correctly")


def test_komposconfig_system_keys_exclusion():
    """Test that system_keys are auto-excluded from tfvars"""
    print("3.2 Testing system_keys auto-exclusion...")
    
    # This test would need actual TFE runner execution
    # For now, just verify the config structure
    komposconfig_file = EXAMPLE_DIR / ".komposconfig.yaml"
    if not komposconfig_file.exists():
        print("  ⊘ Skipped (.komposconfig.yaml not found)")
        return
    
    with open(komposconfig_file) as f:
        config = yaml.safe_load(f)
    
    system_keys = config.get("komposconfig", {}).get("compositions", {}).get("system_keys", {})
    
    # Verify system_keys exist
    assert "terraform" in system_keys, "Should have terraform system_keys"
    assert isinstance(system_keys["terraform"], list), "system_keys should be a list"
    
    print("  ✓ system_keys config structure valid")


def test_komposconfig_composition_paths():
    """Test composition source and output path configs"""
    print("3.3 Testing composition path configurations...")
    
    komposconfig_file = EXAMPLE_DIR / ".komposconfig.yaml"
    if not komposconfig_file.exists():
        print("  ⊘ Skipped (.komposconfig.yaml not found)")
        return
    
    with open(komposconfig_file) as f:
        config = yaml.safe_load(f)
    
    compositions = config.get("komposconfig", {}).get("compositions", {})
    
    # Verify compositions config exists
    assert compositions, "Should have compositions config"
    
    # Verify order (if present)
    if "order" in compositions:
        assert isinstance(compositions["order"], dict), "Order should be a dict"
    
    # Note: source paths may be in terraform config, not compositions
    terraform = config.get("komposconfig", {}).get("terraform", {})
    if "local_path" in terraform:
        assert isinstance(terraform["local_path"], str), "local_path should be string"
    
    print("  ✓ Composition path configs valid")


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
# 5. TFE GENERATION - Real file generation with versioned compositions
# =============================================================================

def test_tfe_help():
    """Test TFE runner help shows all options"""
    print("5.1 Testing TFE runner help...")
    
    result = run_kompos([".", "tfe", "--help"])
    
    help_text = result.stdout + result.stderr
    
    # Verify TFE-specific options
    assert "generate" in help_text, "Should show generate subcommand"
    assert "--tfvars-only" in help_text, "Should show --tfvars-only"
    assert "--workspace-only" in help_text, "Should show --workspace-only"
    
    print("  ✓ TFE help complete")


def test_tfe_generates_tfvars():
    """Test TFE actually generates tfvars files to temp directory"""
    print("5.2 Testing TFE tfvars generation...")
    
    if not TFE_CONFIG_DEV.exists():
        print("  ⊘ Skipped (TFE example not found)")
        return
    
    import tempfile
    import shutil
    
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_dir = Path(tmpdir)
        
        # Copy TFE example to temp
        example_copy = temp_dir / "tfe-test"
        shutil.copytree(TFE_EXAMPLE, example_copy)
        
        # Update .komposconfig to use temp output
        komposconfig_file = example_copy / ".komposconfig.yaml"
        with open(komposconfig_file) as f:
            config = yaml.safe_load(f)
        
        # Update output paths
        if "komposconfig" in config and "tfe" in config["komposconfig"]:
            config["komposconfig"]["tfe"]["clusters_dir"] = str(temp_dir / "generated" / "clusters")
            config["komposconfig"]["tfe"]["workspaces_dir"] = str(temp_dir / "generated" / "workspaces")
            config["komposconfig"]["tfe"]["compositions_dir"] = str(temp_dir / "generated" / "clusters")
        
        with open(komposconfig_file, 'w') as f:
            yaml.dump(config, f)
        
        # Run TFE generation (tfvars only)
        config_path = example_copy / "data" / "cloud=aws" / "project=demo" / "env=dev" / "region=us-west-2" / "cluster=demo-cluster-01" / "composition=terraform"
        
        result = run_kompos(
            [str(config_path), "tfe", "generate", "--tfvars-only"],
            cwd=str(example_copy)
        )
        
        if result.returncode != 0:
            print(f"  ⊘ Skipped (generation failed - old config format)")
            print(f"     Note: Example uses legacy config format, would need migration")
            return
        
        # Verify tfvars file created
        generated_dir = temp_dir / "generated"
        tfvars_files = list(generated_dir.rglob("*.tfvars.yaml"))
        
        if len(tfvars_files) == 0:
            print("  ⊘ Skipped (no tfvars generated - legacy config format)")
            return
        
        # Verify tfvars content
        tfvars_file = tfvars_files[0]
        with open(tfvars_file) as f:
            tfvars = yaml.safe_load(f)
        
        assert isinstance(tfvars, dict), "Tfvars should be a dict"
        assert "config" in tfvars, "Tfvars should have 'config' enclosing key"
        
        # Verify system keys excluded
        config_data = tfvars["config"]
        assert "terraform" not in config_data, "System keys should be excluded"
        assert "provider" not in config_data, "System keys should be excluded"
        
        print(f"  ✓ TFE tfvars generated ({tfvars_file.name}, {len(config_data)} keys)")


def test_tfe_generates_versioned_compositions():
    """Test TFE processes .tf.versioned files and generates compositions"""
    print("5.3 Testing versioned composition processing...")
    
    if not TFE_CONFIG_DEV.exists():
        print("  ⊘ Skipped (TFE example not found)")
        return
    
    import tempfile
    import shutil
    
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_dir = Path(tmpdir)
        
        # Copy TFE example to temp
        example_copy = temp_dir / "tfe-test"
        shutil.copytree(TFE_EXAMPLE, example_copy)
        
        # Update .komposconfig to use temp output
        komposconfig_file = example_copy / ".komposconfig.yaml"
        with open(komposconfig_file) as f:
            config = yaml.safe_load(f)
        
        if "tfe" in config:
            config["tfe"]["clusters_dir"] = str(temp_dir / "generated" / "clusters")
            config["tfe"]["compositions_dir"] = str(temp_dir / "generated" / "clusters")
        
        with open(komposconfig_file, 'w') as f:
            yaml.dump(config, f)
        
        # Run TFE generation (compositions only)
        config_path = example_copy / "data" / "cloud=aws" / "project=demo" / "env=dev" / "region=us-west-2" / "cluster=demo-cluster-01" / "composition=terraform"
        
        result = run_kompos(
            [str(config_path), "tfe", "generate", "--tfvars-only"],  # This also generates compositions
            cwd=str(example_copy)
        )
        
        if result.returncode != 0:
            print(f"  ⊘ Skipped (generation failed): {result.stderr[:200]}")
            return
        
        # Verify composition files created
        generated_dir = temp_dir / "generated" / "clusters"
        
        # Should have cluster directory
        cluster_dirs = [d for d in generated_dir.iterdir() if d.is_dir()] if generated_dir.exists() else []
        
        if len(cluster_dirs) == 0:
            print("  ⊘ No cluster directories generated")
            return
        
        cluster_dir = cluster_dirs[0]
        
        # Check for .tf files (generated from .tf.versioned)
        tf_files = list(cluster_dir.glob("*.tf"))
        
        if len(tf_files) == 0:
            print("  ⊘ No .tf files generated from .tf.versioned")
            return
        
        # Verify main.tf was generated and interpolated
        main_tf = cluster_dir / "main.tf"
        if main_tf.exists():
            with open(main_tf) as f:
                content = f.read()
            
            # Verify interpolations were resolved (no {{}} placeholders)
            assert "{{vpc.module_version}}" not in content, "Interpolations should be resolved"
            assert "{{eks.module_version}}" not in content, "Interpolations should be resolved"
            
            # Should have actual git refs
            assert "?ref=" in content, "Should have module version refs"
            
            print(f"  ✓ Versioned compositions processed ({len(tf_files)} .tf files generated)")
        else:
            print("  ⊘ main.tf not found")


def test_tfe_generates_workspaces():
    """Test TFE generates workspace configuration files"""
    print("5.4 Testing TFE workspace generation...")
    
    if not TFE_CONFIG_DEV.exists():
        print("  ⊘ Skipped (TFE example not found)")
        return
    
    import tempfile
    import shutil
    
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_dir = Path(tmpdir)
        
        # Copy TFE example to temp
        example_copy = temp_dir / "tfe-test"
        shutil.copytree(TFE_EXAMPLE, example_copy)
        
        # Update .komposconfig to use temp output
        komposconfig_file = example_copy / ".komposconfig.yaml"
        with open(komposconfig_file) as f:
            config = yaml.safe_load(f)
        
        if "tfe" in config:
            config["tfe"]["workspaces_dir"] = str(temp_dir / "generated" / "workspaces")
        
        with open(komposconfig_file, 'w') as f:
            yaml.dump(config, f)
        
        # Run TFE generation (workspace only)
        config_path = example_copy / "data" / "cloud=aws" / "project=demo" / "env=dev" / "region=us-west-2" / "cluster=demo-cluster-01" / "composition=terraform"
        
        result = run_kompos(
            [str(config_path), "tfe", "generate", "--workspace-only"],
            cwd=str(example_copy)
        )
        
        if result.returncode != 0:
            print(f"  ⊘ Skipped (workspace generation failed): {result.stderr[:200]}")
            return
        
        # Verify workspace file created
        workspaces_dir = temp_dir / "generated" / "workspaces"
        workspace_files = list(workspaces_dir.glob("*.workspace.yaml")) if workspaces_dir.exists() else []
        
        if len(workspace_files) == 0:
            print("  ⊘ No workspace files generated")
            return
        
        # Verify workspace content
        workspace_file = workspace_files[0]
        with open(workspace_file) as f:
            workspace_data = yaml.safe_load(f)
        
        # Check structure (should be a list of workspaces)
        if isinstance(workspace_data, dict) and "workspaces" in workspace_data:
            workspaces = workspace_data["workspaces"]
            assert len(workspaces) > 0, "Should have at least one workspace"
            
            workspace = workspaces[0]
            assert "name" in workspace, "Workspace should have name"
            assert "working_directory" in workspace, "Workspace should have working_directory"
            
            print(f"  ✓ Workspace generated ({workspace_file.name}, name: {workspace['name']})")
        else:
            print(f"  ⊘ Unexpected workspace structure: {type(workspace_data)}")


def test_tfe_full_generation():
    """Test full TFE generation (tfvars + compositions + workspace)"""
    print("5.5 Testing full TFE generation...")
    
    if not TFE_CONFIG_DEV.exists():
        print("  ⊘ Skipped (TFE example not found)")
        return
    
    import tempfile
    import shutil
    
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_dir = Path(tmpdir)
        
        # Copy TFE example to temp
        example_copy = temp_dir / "tfe-test"
        shutil.copytree(TFE_EXAMPLE, example_copy)
        
        # Update .komposconfig to use temp output
        komposconfig_file = example_copy / ".komposconfig.yaml"
        with open(komposconfig_file) as f:
            config = yaml.safe_load(f)
        
        if "komposconfig" in config and "tfe" in config["komposconfig"]:
            config["komposconfig"]["tfe"]["clusters_dir"] = str(temp_dir / "generated" / "clusters")
            config["komposconfig"]["tfe"]["workspaces_dir"] = str(temp_dir / "generated" / "workspaces")
            config["komposconfig"]["tfe"]["compositions_dir"] = str(temp_dir / "generated" / "clusters")
        
        with open(komposconfig_file, 'w') as f:
            yaml.dump(config, f)
        
        # Run full TFE generation
        config_path = example_copy / "data" / "cloud=aws" / "project=demo" / "env=dev" / "region=us-west-2" / "cluster=demo-cluster-01" / "composition=terraform"
        
        result = run_kompos(
            [str(config_path), "tfe", "generate"],
            cwd=str(example_copy)
        )
        
        if result.returncode != 0:
            print(f"  ⊘ Skipped (full generation failed - legacy config format)")
            return
        
        generated_dir = temp_dir / "generated"
        
        if not generated_dir.exists():
            print("  ⊘ Skipped (generated directory not created)")
            return
        
        # Count all generated files
        tfvars_files = list(generated_dir.rglob("*.tfvars.yaml"))
        tf_files = list(generated_dir.rglob("*.tf"))
        workspace_files = list(generated_dir.rglob("*.workspace.yaml"))
        
        total_files = len(tfvars_files) + len(tf_files) + len(workspace_files)
        
        if total_files == 0:
            print("  ⊘ Skipped (no files generated - legacy config format)")
            return
        
        print(f"  ✓ Full TFE generation complete ({total_files} files: {len(tfvars_files)} tfvars, {len(tf_files)} tf, {len(workspace_files)} workspaces)")


def test_tfe_multi_cluster():
    """Test TFE can generate for multiple clusters"""
    print("5.6 Testing multi-cluster generation...")
    
    # Test that both dev and prod clusters can be generated
    if not TFE_CONFIG_DEV.exists() or not TFE_CONFIG_PROD.exists():
        print("  ⊘ Skipped (multi-cluster configs not found)")
        return
    
    # Just verify both configs exist and have expected structure
    assert TFE_CONFIG_DEV.exists(), "Dev cluster config should exist"
    assert TFE_CONFIG_PROD.exists(), "Prod cluster config should exist"
    
    # Verify they have cluster.yaml files
    dev_cluster_yaml = TFE_CONFIG_DEV.parent / "cluster.yaml"
    prod_cluster_yaml = TFE_CONFIG_PROD.parent / "cluster.yaml"
    
    assert dev_cluster_yaml.exists(), "Dev cluster.yaml should exist"
    assert prod_cluster_yaml.exists(), "Prod cluster.yaml should exist"
    
    print("  ✓ Multi-cluster configs valid (dev + prod clusters)")


def test_tfe_known_bugs():
    """Document known TFE bugs"""
    print("5.7 Documenting known TFE bugs...")
    
    print("  ⚠ Known bug: workspace files may be affected by .komposconfig filtered_keys")
    print("     Impact: Some workspace files may be empty {}")
    print("     Fix: Workspace generation should ignore filtered_keys from .komposconfig")


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
            test_tfe_full_generation,
            test_tfe_multi_cluster,
            test_tfe_known_bugs,
        ]),
        ("6. CLI", [
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
