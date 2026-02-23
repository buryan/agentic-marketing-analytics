"""Tests for JSON schema validity and enum consistency."""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

SCHEMAS_DIR = PROJECT_ROOT / "config" / "schemas"

from run_analysis import CHANNEL_GROUPS, GROUP_CHANNELS


def _load_schema(name: str) -> dict:
    path = SCHEMAS_DIR / name
    assert path.exists(), f"Schema file not found: {name}"
    with open(path) as f:
        return json.load(f)


# ── Schema Parsing ───────────────────────────────────────────────────


def test_channel_output_schema_valid_json():
    _load_schema("channel-output.json")


def test_group_synthesis_schema_valid_json():
    _load_schema("group-synthesis-output.json")


def test_hypothesis_schema_valid_json():
    _load_schema("hypothesis-output.json")


def test_synthesis_schema_valid_json():
    _load_schema("synthesis-output.json")


# ── Enum Consistency ─────────────────────────────────────────────────


def test_channel_enum_covers_all_channels():
    """channel-output.json channel enum must include all channels from CHANNEL_GROUPS."""
    schema = _load_schema("channel-output.json")
    channel_enum = schema["properties"]["channel"]["enum"]

    for channel in CHANNEL_GROUPS:
        assert channel in channel_enum, (
            f"Channel '{channel}' from CHANNEL_GROUPS missing from channel-output.json enum"
        )


def test_channel_group_enum_covers_all_groups():
    """channel-output.json channel_group enum must include all groups from GROUP_CHANNELS."""
    schema = _load_schema("channel-output.json")
    group_enum = schema["properties"]["channel_group"]["enum"]

    for group in GROUP_CHANNELS:
        assert group in group_enum, (
            f"Group '{group}' from GROUP_CHANNELS missing from channel-output.json channel_group enum"
        )


def test_group_synthesis_group_enum_covers_all_groups():
    """group-synthesis-output.json group enum must include all groups from GROUP_CHANNELS."""
    schema = _load_schema("group-synthesis-output.json")
    group_enum = schema["properties"]["group"]["enum"]

    for group in GROUP_CHANNELS:
        assert group in group_enum, (
            f"Group '{group}' from GROUP_CHANNELS missing from group-synthesis-output.json enum"
        )
