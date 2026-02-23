"""Tests for scripts/validate_data.py mapping consistency."""

import sys
from pathlib import Path

import pytest

try:
    import yaml as yaml_mod
except ImportError:
    yaml_mod = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from preprocess import SOURCE_SIGNATURES
from validate_data import SOURCE_RULES_MAP, SOURCE_SCHEMA_MAP

SCHEMAS_DIR = PROJECT_ROOT / "data" / "schemas"
CONFIG_DIR = PROJECT_ROOT / "config"


# ── Schema Map Coverage ──────────────────────────────────────────────


def test_every_preprocess_source_has_schema_entry():
    """Every source in preprocess SOURCE_SIGNATURES should have a matching entry in
    validate_data SOURCE_SCHEMA_MAP."""
    for source_name, _ in SOURCE_SIGNATURES:
        assert source_name in SOURCE_SCHEMA_MAP, (
            f"Source '{source_name}' in preprocess.py SOURCE_SIGNATURES "
            f"but missing from validate_data.py SOURCE_SCHEMA_MAP"
        )


def test_every_schema_entry_has_yaml_file():
    """Every schema value in SOURCE_SCHEMA_MAP should point to an existing .yaml file."""
    seen = set()
    for source, schema_key in SOURCE_SCHEMA_MAP.items():
        if schema_key in seen:
            continue
        seen.add(schema_key)
        schema_path = SCHEMAS_DIR / f"{schema_key}.yaml"
        assert schema_path.exists(), (
            f"Schema file '{schema_key}.yaml' referenced by SOURCE_SCHEMA_MAP['{source}'] "
            f"does not exist at {schema_path}"
        )


# ── Rules Map Coverage ───────────────────────────────────────────────


def test_every_preprocess_source_has_rules_entry():
    """Every source in preprocess SOURCE_SIGNATURES should have a matching entry in
    validate_data SOURCE_RULES_MAP."""
    for source_name, _ in SOURCE_SIGNATURES:
        assert source_name in SOURCE_RULES_MAP, (
            f"Source '{source_name}' in preprocess.py SOURCE_SIGNATURES "
            f"but missing from validate_data.py SOURCE_RULES_MAP"
        )


@pytest.mark.skipif(yaml_mod is None, reason="pyyaml not installed")
def test_every_rules_entry_has_config_key():
    """Every rules key in SOURCE_RULES_MAP should exist in data-quality-rules.yaml."""
    rules_path = CONFIG_DIR / "data-quality-rules.yaml"
    assert rules_path.exists(), "data-quality-rules.yaml not found"

    with open(rules_path) as f:
        rules = yaml_mod.safe_load(f) or {}

    seen = set()
    for source, rules_key in SOURCE_RULES_MAP.items():
        if rules_key in seen:
            continue
        seen.add(rules_key)
        assert rules_key in rules, (
            f"Rules key '{rules_key}' referenced by SOURCE_RULES_MAP['{source}'] "
            f"does not exist in data-quality-rules.yaml"
        )
