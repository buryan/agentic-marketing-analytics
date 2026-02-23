"""Tests for run_analysis.py routing logic and mapping consistency."""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from run_analysis import (
    CHANNEL_AGENT_MAP,
    CHANNEL_BASELINE_MAP,
    CHANNEL_GROUPS,
    FILE_PREFIX_MAP,
    GROUP_CHANNELS,
    GROUP_SYNTHESIS_MAP,
    ROUTING_TABLE,
    TEMPLATE_RULES,
    classify_query,
    determine_synthesis_levels,
    select_template,
)


# ── Mapping Consistency ──────────────────────────────────────────────


def test_all_channels_have_agent():
    """Every channel in CHANNEL_GROUPS must have an entry in CHANNEL_AGENT_MAP."""
    for channel in CHANNEL_GROUPS:
        assert channel in CHANNEL_AGENT_MAP, f"Channel '{channel}' missing from CHANNEL_AGENT_MAP"


def test_all_channels_have_baseline():
    """Every channel in CHANNEL_GROUPS must have an entry in CHANNEL_BASELINE_MAP."""
    for channel in CHANNEL_GROUPS:
        assert channel in CHANNEL_BASELINE_MAP, f"Channel '{channel}' missing from CHANNEL_BASELINE_MAP"


def test_all_groups_have_synthesis_entry():
    """Every group in GROUP_CHANNELS must have an entry in GROUP_SYNTHESIS_MAP (even if None)."""
    for group in GROUP_CHANNELS:
        assert group in GROUP_SYNTHESIS_MAP, f"Group '{group}' missing from GROUP_SYNTHESIS_MAP"


def test_channel_groups_consistent_with_group_channels():
    """CHANNEL_GROUPS and GROUP_CHANNELS must be consistent inverses."""
    # Every channel in CHANNEL_GROUPS must appear in its group's list in GROUP_CHANNELS
    for channel, group in CHANNEL_GROUPS.items():
        assert group in GROUP_CHANNELS, f"Group '{group}' from CHANNEL_GROUPS not in GROUP_CHANNELS"
        assert channel in GROUP_CHANNELS[group], (
            f"Channel '{channel}' mapped to group '{group}' in CHANNEL_GROUPS "
            f"but not in GROUP_CHANNELS['{group}']"
        )

    # Every channel listed in GROUP_CHANNELS must have the correct group in CHANNEL_GROUPS
    for group, channels in GROUP_CHANNELS.items():
        for ch in channels:
            assert ch in CHANNEL_GROUPS, f"Channel '{ch}' in GROUP_CHANNELS['{group}'] not in CHANNEL_GROUPS"
            assert CHANNEL_GROUPS[ch] == group, (
                f"Channel '{ch}' in GROUP_CHANNELS['{group}'] but CHANNEL_GROUPS['{ch}'] = '{CHANNEL_GROUPS[ch]}'"
            )


def test_agent_prompt_files_exist():
    """All agent prompt files referenced in CHANNEL_AGENT_MAP must exist."""
    for channel, agent_path in CHANNEL_AGENT_MAP.items():
        full_path = PROJECT_ROOT / agent_path
        assert full_path.exists(), f"Agent prompt file missing for '{channel}': {agent_path}"


def test_group_synthesis_prompt_files_exist():
    """All group synthesis prompt files (non-None) must exist."""
    for group, agent_path in GROUP_SYNTHESIS_MAP.items():
        if agent_path is not None:
            full_path = PROJECT_ROOT / agent_path
            assert full_path.exists(), f"Group synthesis prompt missing for '{group}': {agent_path}"


def test_baseline_files_exist():
    """All baseline files must exist on disk."""
    seen = set()
    for channel, baseline_path in CHANNEL_BASELINE_MAP.items():
        if baseline_path in seen:
            continue
        seen.add(baseline_path)
        full_path = PROJECT_ROOT / baseline_path
        assert full_path.exists(), f"Baseline file missing for '{channel}': {baseline_path}"


# ── Keyword Routing ──────────────────────────────────────────────────


def test_sem_routing():
    result = classify_query("How did SEM perform last week?")
    assert "sem" in result["channels"]
    assert "paid" in result["groups"]


def test_display_routing():
    result = classify_query("Show me display campaign performance")
    assert "display" in result["channels"]


def test_email_routing():
    result = classify_query("How is email performing?")
    assert "email" in result["channels"]
    assert "lifecycle" in result["groups"]


def test_seo_routing():
    result = classify_query("Organic search rankings and GSC data")
    assert "seo" in result["channels"]
    assert "organic" in result["groups"]


def test_crm_group_routing():
    result = classify_query("Show me CRM lifecycle performance")
    assert "email" in result["channels"]
    assert "push_notification" in result["channels"]
    assert "sms" in result["channels"]


def test_paid_group_routing():
    result = classify_query("How are paid channels performing?")
    channels = result["channels"]
    assert "sem" in channels
    assert "brand_campaign" in channels
    assert "display" in channels
    assert "metasearch" in channels
    assert "affiliate" in channels


def test_promo_routing():
    result = classify_query("What is the promo ROI for our discount campaign?")
    assert "promo" in result["channels"]
    assert "pricing" in result["groups"]


def test_all_channels_routing():
    result = classify_query("Give me an overall view of all channels")
    assert result["all_channels"] is True


def test_fallback_routing():
    result = classify_query("xyzzy foobar nonsense")
    assert result["match_type"] == "fallback"
    assert result["channels"] == []


# ── Template Selection ───────────────────────────────────────────────


def test_anomaly_template():
    assert select_template("any anomaly in the data?") == "templates/anomaly-alert.md"
    assert select_template("flag unusual trends") == "templates/anomaly-alert.md"


def test_comparison_template():
    assert select_template("compare sem vs display") == "templates/period-comparison.md"
    assert select_template("week over week comparison") == "templates/period-comparison.md"


def test_default_template():
    assert select_template("how did sem perform?") == "templates/weekly-report.md"


# ── Synthesis Logic ──────────────────────────────────────────────────


def test_single_channel_no_synthesis():
    groups, top = determine_synthesis_levels(["sem"])
    assert groups == []
    assert top is False


def test_same_group_multi_channel_synthesis():
    groups, top = determine_synthesis_levels(["sem", "display", "affiliate"])
    assert "paid" in groups
    assert top is False


def test_multi_group_synthesis():
    groups, top = determine_synthesis_levels(["sem", "display", "email", "push_notification"])
    assert "paid" in groups
    assert "lifecycle" in groups
    assert top is True


def test_no_synthesis_for_thin_groups():
    """Distribution and pricing groups should not trigger group synthesis (None in map)."""
    groups, top = determine_synthesis_levels(["distribution", "paid_user_referral"])
    assert "distribution" not in groups  # GROUP_SYNTHESIS_MAP["distribution"] is None
