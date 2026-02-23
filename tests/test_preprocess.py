"""Tests for scripts/preprocess.py source detection, column aliasing, and HALO splitting."""

import sys
import tempfile
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from preprocess import (
    COLUMN_ALIASES,
    HALO_CHANNEL_MAP,
    SOURCE_SIGNATURES,
    identify_source,
    parse_space_number,
    split_halo_file,
    standardize_columns,
)
from run_analysis import CHANNEL_GROUPS

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


# ── Source Detection ─────────────────────────────────────────────────


def test_detect_google_ads():
    df = pd.DataFrame(columns=["Campaign", "Impressions", "Clicks", "Cost", "Conversions"])
    assert identify_source(df) == "google-ads"


def test_detect_gsc():
    df = pd.DataFrame(columns=["Page", "Impressions", "Clicks", "CTR", "Position"])
    assert identify_source(df) == "gsc"


def test_detect_halo():
    df = pd.DataFrame(columns=["Dimension 1", "Dimension 2", "Activations", "Impressions", "Spend", "M1+VFM"])
    assert identify_source(df) == "halo"


def test_detect_email():
    df = pd.DataFrame(columns=["Campaign", "Sent", "Delivered", "Opens", "Clicks"])
    assert identify_source(df) == "email"


def test_detect_affiliate():
    df = pd.DataFrame(columns=["Publisher", "Clicks", "Commission"])
    assert identify_source(df) == "affiliate"


def test_detect_display():
    df = pd.DataFrame(columns=["Campaign", "Impressions", "Cost"])
    assert identify_source(df) == "display"


def test_detect_promo():
    df = pd.DataFrame(columns=["Promo Name", "Orders", "Revenue", "Discount Amount"])
    assert identify_source(df) == "promo"


def test_detect_metasearch():
    df = pd.DataFrame(columns=["Campaign", "Impressions", "Clicks", "Cost", "Bookings"])
    assert identify_source(df) == "metasearch"


def test_unknown_source_returns_none():
    df = pd.DataFrame(columns=["Foo", "Bar", "Baz"])
    assert identify_source(df) is None


# ── Column Aliases ───────────────────────────────────────────────────


def test_column_alias_maps_impr():
    df = pd.DataFrame({"Impr.": [100], "Clicks": [10]})
    result = standardize_columns(df)
    assert "Impressions" in result.columns


def test_column_alias_maps_spend_to_cost():
    df = pd.DataFrame({"spend": [50.0]})
    result = standardize_columns(df)
    assert "Cost" in result.columns


# ── HALO Channel Map ────────────────────────────────────────────────


def test_halo_channel_map_covers_system_channels():
    """HALO_CHANNEL_MAP output values should cover all channels in CHANNEL_GROUPS
    (except channels with separate data feeds or no agents)."""
    halo_channel_ids = set(HALO_CHANNEL_MAP.values())
    system_channels = set(CHANNEL_GROUPS.keys())
    # Channels not in HALO feed: unattributed (no agents) + promo (separate data feed)
    not_in_halo = {"direct", "unknown", "unknown_utm", "mobile_app_downloads", "promo"}
    expected = system_channels - not_in_halo

    missing = expected - halo_channel_ids
    assert not missing, f"System channels missing from HALO_CHANNEL_MAP: {missing}"


# ── Space Number Parsing ────────────────────────────────────────────


def test_parse_space_number_basic():
    assert parse_space_number("1 000") == 1000.0


def test_parse_space_number_large():
    assert parse_space_number("12 345 678") == 12345678.0


def test_parse_space_number_hashes():
    import math
    assert math.isnan(parse_space_number("#########"))


def test_parse_space_number_nan():
    import math
    assert math.isnan(parse_space_number(float("nan")))


# ── HALO File Splitting ─────────────────────────────────────────────


def test_split_halo_fixture():
    """Split the sample HALO fixture and verify output."""
    sample = FIXTURES_DIR / "sample_halo.csv"
    assert sample.exists(), f"Fixture not found: {sample}"

    with tempfile.TemporaryDirectory() as tmpdir:
        # Temporarily override DATA_VALIDATED
        import preprocess
        original = preprocess.DATA_VALIDATED
        preprocess.DATA_VALIDATED = Path(tmpdir)
        try:
            result = split_halo_file(sample, dry_run=False)
        finally:
            preprocess.DATA_VALIDATED = original

        assert result["status"] == "success"
        # sample_halo.csv has 3 channels: affiliate, sem, display (+ Total which is filtered)
        assert len(result["output_files"]) == 3

        # Verify the files were written
        written = [Path(f).name for f in result["output_files"]]
        assert any("affiliate" in f for f in written)
        assert any("sem" in f for f in written)
        assert any("display" in f for f in written)

        # Verify each file has 3 rows (3 dates per channel)
        for f in result["output_files"]:
            df = pd.read_csv(f)
            assert len(df) == 3
            assert "Date" in df.columns
            assert "Dimension 1" not in df.columns  # Should be dropped
