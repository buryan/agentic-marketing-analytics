#!/usr/bin/env python3
"""
Marketing Analytics Orchestrator — Master pipeline runner.

Enforces the mandatory 9-step analysis chain:
1. CLASSIFY — Determine intent from user query (keyword match + LLM fallback)
2. PREPROCESS — Standardize new input files (Python script)
3. VALIDATE — Data quality gate (Python script, FAIL = block)
4. DISPATCH — Route to channel agent(s), parallel when possible
5. GROUP SYNTHESIZE — Intra-group synthesis (parallel across groups, if 2+ channels in group)
6. HYPOTHESIZE — Explain metric movements (sequential, after all channels + group synthesis)
7. TOP SYNTHESIZE — Cross-group synthesis (conditional, if 2+ groups)
8. FORMAT — Select template, render output
9. MEMORY UPDATE — Update baselines, log decisions

Usage:
    python run_analysis.py "How did SEM perform last week?"
    python run_analysis.py "Compare all channels WoW"
    python run_analysis.py "How is email performing?"
    python run_analysis.py --channels sem,display --period 2026-02-10/2026-02-16
    python run_analysis.py --preprocess-only          # just run steps 1-3
    python run_analysis.py --skip-preprocess           # skip steps 1-2 if data is already clean
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Resolve paths relative to project root
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR
DATA_INPUT = PROJECT_ROOT / "data" / "input"
DATA_VALIDATED = PROJECT_ROOT / "data" / "validated"
DATA_PIPELINE = PROJECT_ROOT / "data" / "pipeline"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
AGENTS_DIR = PROJECT_ROOT / "agents"
CONFIG_DIR = PROJECT_ROOT / "config"
MEMORY_DIR = PROJECT_ROOT / "memory"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
SCHEMAS_DIR = PROJECT_ROOT / "config" / "schemas"

# ─────────────────────────────────────────────
# CHANNEL GROUPS & MAPPINGS
# ─────────────────────────────────────────────

CHANNEL_GROUPS = {
    "sem": "paid",
    "brand_campaign": "paid",
    "display": "paid",
    "promoted_social": "paid",
    "metasearch": "paid",
    "affiliate": "paid",
    "email": "lifecycle",
    "push_notification": "lifecycle",
    "sms": "lifecycle",
    "seo": "organic",
    "free_referral": "organic",
    "managed_social": "organic",
    "distribution": "distribution",
    "paid_user_referral": "distribution",
    "promo": "pricing",
}

GROUP_CHANNELS = {
    "paid": ["sem", "brand_campaign", "display", "promoted_social", "metasearch", "affiliate"],
    "lifecycle": ["email", "push_notification", "sms"],
    "organic": ["seo", "free_referral", "managed_social"],
    "distribution": ["distribution", "paid_user_referral"],
    "pricing": ["promo"],
}

CHANNEL_AGENT_MAP = {
    "sem": "agents/paid/sem.md",
    "brand_campaign": "agents/paid/sem.md",
    "display": "agents/paid/display.md",
    "promoted_social": "agents/paid/display.md",
    "metasearch": "agents/paid/metasearch.md",
    "affiliate": "agents/paid/affiliate.md",
    "email": "agents/lifecycle/crm.md",
    "push_notification": "agents/lifecycle/crm.md",
    "sms": "agents/lifecycle/crm.md",
    "seo": "agents/organic/content-seo.md",
    "free_referral": "agents/organic/earned.md",
    "managed_social": "agents/organic/earned.md",
    "distribution": "agents/distribution/distribution.md",
    "paid_user_referral": "agents/distribution/distribution.md",
    "promo": "agents/pricing/promo-impact.md",
}

GROUP_SYNTHESIS_MAP = {
    "paid": "agents/paid/synthesis.md",
    "lifecycle": "agents/lifecycle/synthesis.md",
    "organic": "agents/organic/synthesis.md",
    "distribution": "agents/distribution/synthesis.md",
    "pricing": None,  # Single channel, too thin for group synthesis
}

CHANNEL_BASELINE_MAP = {
    "sem": "memory/baselines/sem-weekly-baselines.md",
    "brand_campaign": "memory/baselines/sem-weekly-baselines.md",
    "display": "memory/baselines/display-weekly-baselines.md",
    "promoted_social": "memory/baselines/display-weekly-baselines.md",
    "metasearch": "memory/baselines/metasearch-weekly-baselines.md",
    "affiliate": "memory/baselines/affiliate-monthly-baselines.md",
    "email": "memory/baselines/email-weekly-baselines.md",
    "push_notification": "memory/baselines/push-weekly-baselines.md",
    "sms": "memory/baselines/sms-weekly-baselines.md",
    "seo": "memory/baselines/seo-weekly-baselines.md",
    "free_referral": "memory/baselines/referral-weekly-baselines.md",
    "managed_social": "memory/baselines/social-weekly-baselines.md",
    "distribution": "memory/baselines/distribution-monthly-baselines.md",
    "paid_user_referral": "memory/baselines/distribution-monthly-baselines.md",
    "promo": "memory/baselines/pricing-weekly-baselines.md",
}

# File prefix -> channel mapping for data detection
FILE_PREFIX_MAP = {
    "google-ads": "sem",
    "brand-campaign": "brand_campaign",
    "gsc": "seo",
    "affiliate": "affiliate",
    "display": "display",
    "social-paid": "promoted_social",
    "metasearch": "metasearch",
    "email": "email",
    "push": "push_notification",
    "sms": "sms",
    "social-organic": "managed_social",
    "referral": "free_referral",
    "distribution": "distribution",
    "referral-program": "paid_user_referral",
    "promo": "promo",
}

# ─────────────────────────────────────────────
# ROUTING TABLE
# ─────────────────────────────────────────────

ROUTING_TABLE = [
    # --- Paid Search ---
    {
        "keywords": ["sem", "google ads", "paid search", "cpc", "roas", "search ads", "adwords"],
        "channels": ["sem"],
    },
    {
        "keywords": ["brand campaign", "branded", "brand search"],
        "channels": ["brand_campaign"],
    },
    # --- Paid Media ---
    {
        "keywords": ["display", "programmatic", "dv360", "cpm", "banner", "viewability"],
        "channels": ["display"],
    },
    {
        "keywords": ["paid social", "social ads", "facebook ads", "instagram ads", "tiktok ads"],
        "channels": ["promoted_social"],
    },
    {
        "keywords": ["metasearch", "hotel ads", "tripadvisor", "trivago", "kayak"],
        "channels": ["metasearch"],
    },
    # --- Affiliate ---
    {
        "keywords": ["affiliate", "publisher", "commission", "epc"],
        "channels": ["affiliate"],
    },
    # --- Lifecycle/CRM ---
    {
        "keywords": ["email", "newsletter", "mailchimp", "braze", "email marketing"],
        "channels": ["email"],
    },
    {
        "keywords": ["push", "push notification", "app notification", "mobile push"],
        "channels": ["push_notification"],
    },
    {
        "keywords": ["sms", "text message", "mms"],
        "channels": ["sms"],
    },
    {
        "keywords": ["crm", "lifecycle", "managed channels", "owned channels", "retention"],
        "channels": ["email", "push_notification", "sms"],
    },
    # --- Organic ---
    {
        "keywords": ["seo", "organic search", "rankings", "gsc", "search console", "position",
                      "crawl", "indexing", "page speed", "core web vitals", "technical seo"],
        "channels": ["seo"],
    },
    {
        "keywords": ["organic social", "social media", "community", "managed social"],
        "channels": ["managed_social"],
    },
    {
        "keywords": ["referral", "word of mouth", "organic referral"],
        "channels": ["free_referral"],
    },
    # --- Distribution ---
    {
        "keywords": ["distribution", "white label", "syndication"],
        "channels": ["distribution"],
    },
    {
        "keywords": ["referral program", "refer a friend", "user referral", "referral incentive"],
        "channels": ["paid_user_referral"],
    },
    # --- Pricing & Promotions ---
    {
        "keywords": ["pricing", "promo", "promotion", "discount", "coupon", "voucher",
                      "deal impact", "offer", "sale event", "promo roi", "promo impact"],
        "channels": ["promo"],
    },
    # --- Self-Contained ---
    {
        "keywords": ["incrementality", "incrementality test", "mroas", "troas test", "split test"],
        "channels": ["sem-incrementality"],
        "self_contained": True,
    },
    # --- Group-Level ---
    {
        "keywords": ["paid", "paid channels", "paid media"],
        "channels": ["sem", "brand_campaign", "display", "promoted_social", "metasearch", "affiliate"],
    },
    {
        "keywords": ["organic", "organic channels"],
        "channels": ["seo", "free_referral", "managed_social"],
    },
    # --- All Channels ---
    {
        "keywords": ["overall", "all channels", "mix", "compare channels", "total",
                      "blended", "portfolio"],
        "channels": [],  # All available
        "all_channels": True,
    },
    {
        "keywords": ["budget", "pacing", "spend"],
        "channels": ["sem", "display", "metasearch", "affiliate"],
    },
    {
        "keywords": ["anomal", "alert", "flag", "unusual"],
        "channels": [],  # All available
        "all_channels": True,
    },
]

# Template selection keywords (checked as substrings of the query)
TEMPLATE_RULES = {
    "anomal": "templates/anomaly-alert.md",  # matches anomaly, anomalies, anomalous
    "alert": "templates/anomaly-alert.md",
    "flag": "templates/anomaly-alert.md",
    "unusual": "templates/anomaly-alert.md",
    "compar": "templates/period-comparison.md",  # matches compare, comparison, comparing
    "versus": "templates/period-comparison.md",
    " vs ": "templates/period-comparison.md",
    "default": "templates/weekly-report.md",
}


# ─────────────────────────────────────────────
# STEP 1: CLASSIFY INTENT
# ─────────────────────────────────────────────

def classify_query(query: str) -> dict:
    """Route a user query to the appropriate channel agents.

    Returns:
        {
            "channels": ["sem", "display", ...],
            "groups": ["paid", "lifecycle", ...],
            "template": "templates/weekly-report.md",
            "self_contained": False,
            "all_channels": False,
            "match_type": "keyword" | "fallback",
            "date_range": {"current": "...", "prior": "..."} | None,
            "comparison_type": "wow" | "mom" | "yoy",
            "geo": "NA" | "INTL" | "ALL"
        }
    """
    query_lower = query.lower().strip()

    # Keyword matching
    best_match = None
    best_match_count = 0

    for route in ROUTING_TABLE:
        match_count = sum(1 for kw in route["keywords"] if kw in query_lower)
        if match_count > best_match_count:
            best_match = route
            best_match_count = match_count

    if best_match and best_match_count > 0:
        channels = best_match["channels"]
        groups = list(set(CHANNEL_GROUPS.get(ch, "") for ch in channels if ch in CHANNEL_GROUPS))
        result = {
            "channels": channels,
            "groups": [g for g in groups if g],
            "self_contained": best_match.get("self_contained", False),
            "all_channels": best_match.get("all_channels", False),
            "match_type": "keyword",
        }
    else:
        # Fallback: no keyword match. Default to listing available data.
        result = {
            "channels": [],
            "groups": [],
            "self_contained": False,
            "all_channels": False,
            "match_type": "fallback",
        }

    # Determine template
    result["template"] = select_template(query_lower)

    # Parse date range from query
    result["date_range"] = parse_date_range(query_lower)

    # Parse comparison type
    result["comparison_type"] = parse_comparison_type(query_lower)

    # Parse geo filter
    result["geo"] = parse_geo(query_lower)

    return result


def select_template(query_lower: str) -> str:
    """Select output template based on query keywords."""
    for keyword, template in TEMPLATE_RULES.items():
        if keyword == "default":
            continue
        if keyword in query_lower:
            return template
    return TEMPLATE_RULES["default"]


def select_template_from_results(query_lower: str, channel_outputs: list[dict]) -> str:
    """Refine template selection based on analysis results.

    If any anomaly has z_score > 2.0, upgrade to anomaly-alert template.
    """
    template = select_template(query_lower)

    # Check if results warrant anomaly template
    if template == TEMPLATE_RULES["default"]:
        for output in channel_outputs:
            anomalies = output.get("anomalies", [])
            for anomaly in anomalies:
                if abs(anomaly.get("z_score", 0)) > 2.0:
                    return TEMPLATE_RULES["anomal"]

    return template


def parse_date_range(query: str) -> dict | None:
    """Extract date range from query string."""
    iso_pattern = r"(\d{4}-\d{2}-\d{2})\s*(?:to|through|thru|-)\s*(\d{4}-\d{2}-\d{2})"
    match = re.search(iso_pattern, query)
    if match:
        return {"current_start": match.group(1), "current_end": match.group(2)}
    return None


def parse_comparison_type(query: str) -> str:
    """Determine comparison type from query."""
    if any(kw in query for kw in ["yoy", "year over year", "vs last year", "year-over-year"]):
        return "yoy"
    if any(kw in query for kw in ["mom", "month over month", "vs last month", "month-over-month"]):
        return "mom"
    return "wow"  # Default: week-over-week


def parse_geo(query: str) -> str:
    """Determine geography filter from query."""
    if any(kw in query for kw in ["intl", "international", "non-us", "global"]):
        return "INTL"
    if re.search(r"\bna\b", query) or any(kw in query for kw in ["north america", "us only", "domestic"]):
        return "NA"
    return "ALL"


# ─────────────────────────────────────────────
# STEP 2: PREPROCESS
# ─────────────────────────────────────────────

def run_preprocessor(dry_run: bool = False) -> dict:
    """Run the preprocessing script on new input files."""
    cmd = [sys.executable, str(SCRIPTS_DIR / "preprocess.py"), "--json"]
    if dry_run:
        cmd.append("--dry-run")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            return {"status": "error", "error": result.stderr}
        return json.loads(result.stdout) if result.stdout.strip() else {"status": "no_output"}
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "Preprocessor timed out after 120s"}
    except json.JSONDecodeError:
        return {"status": "error", "error": f"Invalid JSON from preprocessor: {result.stdout[:200]}"}
    except FileNotFoundError:
        return {"status": "error", "error": "Preprocessor script not found. Run from project root."}


# ─────────────────────────────────────────────
# STEP 3: VALIDATE (DATA QUALITY GATE)
# ─────────────────────────────────────────────

def run_validation() -> dict:
    """Run data quality validation. Returns gate decision."""
    cmd = [sys.executable, str(SCRIPTS_DIR / "validate_data.py"), "--json"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            return {"gate_decision": "BLOCK", "error": result.stderr}
        return json.loads(result.stdout) if result.stdout.strip() else {"gate_decision": "PROCEED"}
    except subprocess.TimeoutExpired:
        return {"gate_decision": "BLOCK", "error": "Validation timed out after 120s"}
    except json.JSONDecodeError:
        return {"gate_decision": "BLOCK", "error": f"Invalid JSON from validator: {result.stdout[:200]}"}
    except FileNotFoundError:
        return {"gate_decision": "BLOCK", "error": "Validation script not found. Run from project root."}


# ─────────────────────────────────────────────
# STEP 4: DISPATCH CHANNEL AGENTS
# ─────────────────────────────────────────────

def get_available_data() -> dict[str, list[str]]:
    """Scan /data/validated/ for available data files, grouped by channel."""
    available = {}
    if not DATA_VALIDATED.exists():
        return available

    for f in DATA_VALIDATED.glob("*.csv"):
        name = f.name.lower()
        for prefix, channel in FILE_PREFIX_MAP.items():
            if name.startswith(prefix):
                available.setdefault(channel, []).append(str(f))
                break

    return available


def filter_channels_by_data(requested_channels: list[str], available_data: dict) -> tuple[list[str], list[str]]:
    """Filter requested channels to only those with available data.

    Returns:
        (active_channels, skipped_channels)
    """
    active = []
    skipped = []
    for ch in requested_channels:
        if ch in available_data:
            active.append(ch)
        else:
            skipped.append(ch)
    return active, skipped


def determine_synthesis_levels(active_channels: list[str]) -> tuple[list[str], bool]:
    """Determine which synthesis agents to run.

    Returns:
        (group_synthesis_groups, needs_top_level_synthesis)
    """
    channels_per_group = {}
    for ch in active_channels:
        group = CHANNEL_GROUPS.get(ch)
        if group:
            channels_per_group.setdefault(group, []).append(ch)

    # Group synthesis: run for any group with 2+ active channels AND a synthesis agent
    group_synthesis = []
    for group, channels in channels_per_group.items():
        if len(channels) >= 2 and GROUP_SYNTHESIS_MAP.get(group):
            group_synthesis.append(group)

    # Top-level synthesis: run if 2+ groups are active
    active_groups = set(channels_per_group.keys())
    needs_top_synthesis = len(active_groups) >= 2

    return group_synthesis, needs_top_synthesis


def build_agent_context(channel: str, classification: dict) -> dict:
    """Build the context payload for a channel sub-agent.

    Returns a dict with only the relevant prompt, config, memory, and data
    for this specific channel — not the full payload.
    """
    context = {
        "channel": channel,
        "channel_group": CHANNEL_GROUPS.get(channel),
        "agent_prompt": CHANNEL_AGENT_MAP.get(channel),
        "config": {
            "metrics": str(CONFIG_DIR / "metrics.yaml"),
            "thresholds": str(CONFIG_DIR / "thresholds.yaml"),
            "benchmarks": str(CONFIG_DIR / "benchmarks.yaml"),
        },
        "memory": {
            "baselines": str(PROJECT_ROOT / CHANNEL_BASELINE_MAP.get(channel, "")),
            "known_issues": str(MEMORY_DIR / "known-issues.md"),
            "context": str(MEMORY_DIR / "context.md"),
        },
        "data_files": get_available_data().get(channel, []),
        "date_range": classification.get("date_range"),
        "comparison_type": classification.get("comparison_type", "wow"),
        "geo": classification.get("geo", "ALL"),
        "output_schema": str(SCHEMAS_DIR / "channel-output.json"),
    }

    return context


def build_subagent_prompt(channel: str, context: dict) -> str:
    """Build the prompt string for a channel sub-agent."""
    prompt = f"""You are the {channel.upper()} channel analysis agent.

## Instructions
Read your agent prompt file and follow its analysis process exactly.

## Agent Prompt
Read: {context['agent_prompt']}

## Channel Group
This channel belongs to the **{context.get('channel_group', 'unknown')}** group.

## Reference Files (read these before analysis)
- Metrics definitions: {context['config']['metrics']}
- Thresholds: {context['config']['thresholds']}
- Benchmarks: {context['config']['benchmarks']}
- Baselines: {context['memory']['baselines']}
- Known issues: {context['memory']['known_issues']}
- Business context: {context['memory']['context']}

## Data Files
{chr(10).join(f'- {f}' for f in context['data_files'])}

## Analysis Parameters
- Comparison type: {context['comparison_type']}
- Geo filter: {context['geo']}
- Date range: {context.get('date_range') or 'Use most recent complete period'}

## Output Requirements
Your output MUST be valid JSON conforming to the schema at {context['output_schema']}.

Read the schema file, then produce a JSON output with these fields:
- channel: "{channel}"
- channel_group: "{context.get('channel_group')}"
- geo: your geo filter
- period: "YYYY-MM-DD/YYYY-MM-DD"
- comparison_type: "{context['comparison_type']}"
- summary: array of metric objects (metric, current, prior, delta_pct, benchmark, status)
- top_movers: array of top 5 movers (rank, segment, metric, change_pct, likely_cause)
- anomalies: array of detected anomalies (metric, segment, z_score, direction, value, baseline)
- budget_pacing: object with mtd_spend, monthly_budget, linear_pace, variance_pct, projected_month_end, status (null for non-spend channels)
- data_quality_notes: array of warning strings
- extended_metrics: object with channel-specific KPIs (for CRM: open_rate, click_rate, etc.)

Read the data files, perform your analysis, and return ONLY the JSON output.
Write the JSON output to: {str(DATA_PIPELINE / f'{channel}_output.json')}
"""
    return prompt


def build_group_synthesis_prompt(group: str, channel_outputs: list[dict]) -> str:
    """Build the prompt for a group synthesis sub-agent."""
    outputs_json = json.dumps(channel_outputs, indent=2)
    synthesis_agent = GROUP_SYNTHESIS_MAP.get(group)

    prompt = f"""You are the {group.upper()} Group Synthesis Agent.

## Instructions
Read your agent prompt: {synthesis_agent}

## Reference Files
- Metrics definitions: {str(CONFIG_DIR / 'metrics.yaml')}
- Benchmarks: {str(CONFIG_DIR / 'benchmarks.yaml')}
- Business context: {str(MEMORY_DIR / 'context.md')}

## Channel Analysis Results for {group.upper()} Group
```json
{outputs_json}
```

## Output Requirements
Your output MUST be valid JSON conforming to: {str(SCHEMAS_DIR / 'group-synthesis-output.json')}

Produce JSON with:
- group: "{group}"
- group_summary: total_spend, total_revenue, blended_roas, channels_analyzed, status, top_issue, top_opportunity
- channel_mix: intra-group efficiency table
- contradictions: any data conflicts within the group
- actions: top 3 ICE-scored actions scoped to this group

Write the JSON output to: {str(DATA_PIPELINE / f'{group}_group_synthesis_output.json')}
"""
    return prompt


def build_hypothesis_prompt(channel_outputs: list[dict]) -> str:
    """Build the prompt for the hypothesis sub-agent."""
    outputs_json = json.dumps(channel_outputs, indent=2)

    prompt = f"""You are the Hypothesis Agent.

## Instructions
Read your agent prompt: agents/hypothesis.md

## Reference Files
- Known issues: {str(MEMORY_DIR / 'known-issues.md')}
- Business context: {str(MEMORY_DIR / 'context.md')}
- Decisions log: {str(MEMORY_DIR / 'decisions-log.md')}
- Benchmarks: {str(CONFIG_DIR / 'benchmarks.yaml')}
- Thresholds: {str(CONFIG_DIR / 'thresholds.yaml')}

## Channel Analysis Results
```json
{outputs_json}
```

## Output Requirements
Your output MUST be valid JSON conforming to: {str(SCHEMAS_DIR / 'hypothesis-output.json')}

Read the schema, then produce JSON with:
- hypotheses: array of hypothesis objects for each significant metric move

For each metric with delta_pct > 5% (from thresholds.yaml minimum_delta_to_flag), generate 1-3 hypotheses.
Check memory files FIRST: known issues should be the first hypothesis considered.

Write the JSON output to: {str(DATA_PIPELINE / 'hypothesis_output.json')}
"""
    return prompt


def build_top_synthesis_prompt(group_synthesis_outputs: list[dict], hypothesis_output: dict) -> str:
    """Build the prompt for the top-level cross-group synthesis sub-agent."""
    groups_json = json.dumps(group_synthesis_outputs, indent=2)
    hypothesis_json = json.dumps(hypothesis_output, indent=2)

    prompt = f"""You are the Top-Level Cross-Group Synthesis Agent.

## Instructions
Read your agent prompt: agents/cross-channel/synthesis.md

## Reference Files
- Metrics definitions: {str(CONFIG_DIR / 'metrics.yaml')}
- Business context: {str(MEMORY_DIR / 'context.md')}

## Group Synthesis Results
```json
{groups_json}
```

## Hypothesis Results
```json
{hypothesis_json}
```

## Output Requirements
Your output MUST be valid JSON conforming to: {str(SCHEMAS_DIR / 'synthesis-output.json')}

Produce JSON with:
- groups: array of group summary cards
- attribution_coverage: attributed_revenue_pct, unattributed_channels
- channel_mix: cross-group efficiency table
- contradictions: any cross-group data conflicts
- actions: top 5 ICE-scored action items across all groups

Write the JSON output to: {str(DATA_PIPELINE / 'synthesis_output.json')}
"""
    return prompt


# ─────────────────────────────────────────────
# OUTPUT VALIDATION
# ─────────────────────────────────────────────

def validate_channel_output(output: dict) -> list[str]:
    """Validate a channel agent output against quality rules.

    Returns list of validation errors (empty = valid).
    """
    errors = []

    # Required fields
    for field in ["channel", "geo", "period", "summary", "top_movers", "anomalies", "data_quality_notes"]:
        if field not in output:
            errors.append(f"Missing required field: {field}")

    # Summary validation
    summary = output.get("summary", [])
    if not summary:
        errors.append("Summary array is empty (need at least 1 metric)")

    for i, item in enumerate(summary):
        if "metric" not in item:
            errors.append(f"summary[{i}]: missing 'metric' field")
        if "current" not in item or item["current"] is None:
            errors.append(f"summary[{i}]: missing or null 'current' value")
        if "status" not in item:
            errors.append(f"summary[{i}]: missing 'status' field")
        elif item["status"] not in ("GREEN", "YELLOW", "RED"):
            errors.append(f"summary[{i}]: invalid status '{item['status']}'")

        # Cross-check delta_pct calculation
        if item.get("current") is not None and item.get("prior") is not None and item["prior"] != 0:
            expected_delta = ((item["current"] - item["prior"]) / abs(item["prior"])) * 100
            actual_delta = item.get("delta_pct")
            if actual_delta is not None and abs(expected_delta - actual_delta) > 1:
                errors.append(
                    f"summary[{i}] ({item.get('metric', '?')}): delta_pct mismatch. "
                    f"Expected ~{expected_delta:.1f}%, got {actual_delta}%"
                )

    # Top movers: need at least 1
    if not output.get("top_movers"):
        errors.append("top_movers array is empty (need at least 1)")

    return errors


# ─────────────────────────────────────────────
# MEMORY UPDATE
# ─────────────────────────────────────────────

def update_decisions_log(actions: list[dict], analysis_source: str):
    """Append ICE-scored actions to decisions-log.md."""
    log_path = MEMORY_DIR / "decisions-log.md"

    if not actions:
        return

    timestamp = datetime.now().strftime("%Y-%m-%d")

    new_entries = []
    for action in actions[:5]:  # Top 5 only
        entry = (
            f"| {timestamp} | {analysis_source} | "
            f"{action.get('action', 'N/A')} | "
            f"{action.get('rationale', 'N/A')} | "
            f"Pending | Open |"
        )
        new_entries.append(entry)

    if new_entries:
        with open(log_path, "a") as f:
            for entry in new_entries:
                f.write(entry + "\n")


# ─────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────

def run_pipeline(query: str = "", channels: list[str] | None = None,
                 period: str | None = None, skip_preprocess: bool = False,
                 preprocess_only: bool = False, dry_run: bool = False) -> dict:
    """Execute the full 9-step analysis pipeline.

    Returns a dict with results from each step.
    """
    pipeline_result = {
        "query": query,
        "steps": {},
        "status": "running",
        "started_at": datetime.now().isoformat(),
    }

    # Ensure pipeline directory exists
    DATA_PIPELINE.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Classify ──
    print("\n[1/9] CLASSIFY — Determining analysis intent...")
    if channels:
        groups = list(set(CHANNEL_GROUPS.get(ch, "") for ch in channels if ch in CHANNEL_GROUPS))
        classification = {
            "channels": channels,
            "groups": [g for g in groups if g],
            "self_contained": False,
            "all_channels": False,
            "match_type": "explicit",
            "template": select_template(query.lower()),
            "date_range": parse_date_range(period or ""),
            "comparison_type": parse_comparison_type(query.lower()),
            "geo": parse_geo(query.lower()),
        }
    else:
        classification = classify_query(query)

    pipeline_result["steps"]["classify"] = classification
    print(f"  Channels: {classification['channels'] or '(auto-detect from available data)'}")
    print(f"  Groups: {classification.get('groups', [])}")
    print(f"  Template: {classification['template']}")
    print(f"  Comparison: {classification['comparison_type']}")
    print(f"  Geo: {classification['geo']}")
    print(f"  Match type: {classification['match_type']}")

    if classification["match_type"] == "fallback" and not channels and not preprocess_only:
        available = get_available_data()
        if available:
            print(f"\n  No keyword match. Available data sources: {list(available.keys())}")
            print("  Specify --channels or include channel keywords in your query.")
        else:
            print(f"\n  No keyword match and no validated data available.")
            print(f"  Add data files to {DATA_INPUT}/ and re-run.")
        pipeline_result["status"] = "no_match"
        return pipeline_result

    # ── Step 2: Preprocess ──
    if not skip_preprocess:
        print("\n[2/9] PREPROCESS — Standardizing input files...")
        preprocess_result = run_preprocessor(dry_run=dry_run)
        pipeline_result["steps"]["preprocess"] = preprocess_result

        if isinstance(preprocess_result, list):
            success = sum(1 for r in preprocess_result if r.get("status") == "success")
            errors = sum(1 for r in preprocess_result if r.get("status") == "error")
            print(f"  Processed: {success} success, {errors} errors")
        elif isinstance(preprocess_result, dict):
            if preprocess_result.get("status") == "no_files":
                print("  No new files to preprocess")
            elif preprocess_result.get("status") == "error":
                print(f"  Error: {preprocess_result.get('error', 'unknown')}")
    else:
        print("\n[2/9] PREPROCESS — Skipped (--skip-preprocess)")
        pipeline_result["steps"]["preprocess"] = {"status": "skipped"}

    if preprocess_only:
        pipeline_result["status"] = "preprocess_only"
        print("\n[3-9] Skipped (--preprocess-only)")
        return pipeline_result

    # ── Step 3: Validate ──
    print("\n[3/9] VALIDATE — Running data quality checks...")
    validation_result = run_validation()
    pipeline_result["steps"]["validate"] = validation_result

    gate = validation_result.get("gate_decision", "PROCEED")
    print(f"  Gate decision: {gate}")

    if gate == "BLOCK":
        print("  BLOCKED: Data quality issues must be resolved before analysis.")
        for caveat in validation_result.get("caveats", []):
            print(f"    - {caveat}")
        pipeline_result["status"] = "blocked_by_quality"
        return pipeline_result

    if gate == "PROCEED_WITH_CAVEATS":
        print("  Proceeding with caveats:")
        for caveat in validation_result.get("caveats", []):
            print(f"    - {caveat}")

    # ── Step 4: Dispatch ──
    print("\n[4/9] DISPATCH — Routing to channel agents...")
    available_data = get_available_data()
    if classification.get("all_channels"):
        requested = list(available_data.keys())
    else:
        requested = classification["channels"] or list(available_data.keys())
    active_channels, skipped = filter_channels_by_data(requested, available_data)

    if skipped:
        print(f"  Skipped (no data): {skipped}")
    if not active_channels:
        print("  No channels with available data. Add data files and re-run.")
        pipeline_result["status"] = "no_data"
        return pipeline_result

    print(f"  Active channels: {active_channels}")
    active_groups = list(set(CHANNEL_GROUPS.get(ch, "") for ch in active_channels if ch in CHANNEL_GROUPS))
    active_groups = [g for g in active_groups if g]
    print(f"  Active groups: {active_groups}")
    print(f"  Mode: {'parallel' if len(active_channels) > 1 else 'sequential'}")

    # Build contexts and prompts for each channel
    channel_contexts = {}
    for ch in active_channels:
        ctx = build_agent_context(ch, classification)
        channel_contexts[ch] = ctx
        prompt = build_subagent_prompt(ch, ctx)
        prompt_file = DATA_PIPELINE / f"{ch}_prompt.md"
        with open(prompt_file, "w") as f:
            f.write(prompt)
        print(f"  Wrote sub-agent prompt: {prompt_file.name}")

    pipeline_result["steps"]["dispatch"] = {
        "active_channels": active_channels,
        "active_groups": active_groups,
        "skipped_channels": skipped,
        "prompts_written": [f"{ch}_prompt.md" for ch in active_channels],
    }

    # ── Step 5: Group Synthesis ──
    group_synthesis_groups, needs_top_synthesis = determine_synthesis_levels(active_channels)

    if group_synthesis_groups:
        print(f"\n[5/9] GROUP SYNTHESIZE — Preparing group synthesis for: {group_synthesis_groups}")
        for group in group_synthesis_groups:
            group_prompt = build_group_synthesis_prompt(group, [])  # Placeholder
            grp_file = DATA_PIPELINE / f"{group}_group_synthesis_prompt.md"
            with open(grp_file, "w") as f:
                f.write(group_prompt)
            print(f"  Wrote group synthesis prompt: {grp_file.name}")
        pipeline_result["steps"]["group_synthesis"] = {
            "groups": group_synthesis_groups,
            "prompts_written": [f"{g}_group_synthesis_prompt.md" for g in group_synthesis_groups],
        }
    else:
        print(f"\n[5/9] GROUP SYNTHESIZE — Skipped (no group has 2+ active channels)")
        pipeline_result["steps"]["group_synthesis"] = {"status": "skipped"}

    # ── Step 6: Hypothesis prompt ──
    print("\n[6/9] HYPOTHESIZE — Preparing hypothesis agent...")
    hypothesis_prompt = build_hypothesis_prompt([])  # Placeholder; real data comes from step 4 outputs
    hyp_file = DATA_PIPELINE / "hypothesis_prompt.md"
    with open(hyp_file, "w") as f:
        f.write(hypothesis_prompt)
    print(f"  Wrote hypothesis prompt: {hyp_file.name}")
    pipeline_result["steps"]["hypothesis"] = {"prompt_written": str(hyp_file)}

    # ── Step 7: Top-level synthesis prompt (conditional) ──
    if needs_top_synthesis:
        print(f"\n[7/9] TOP SYNTHESIZE — Preparing top-level synthesis (multi-group)...")
        top_synthesis_prompt = build_top_synthesis_prompt([], {})  # Placeholder
        syn_file = DATA_PIPELINE / "top_synthesis_prompt.md"
        with open(syn_file, "w") as f:
            f.write(top_synthesis_prompt)
        print(f"  Wrote top synthesis prompt: {syn_file.name}")
        pipeline_result["steps"]["top_synthesis"] = {"prompt_written": str(syn_file)}
    else:
        print(f"\n[7/9] TOP SYNTHESIZE — Skipped ({'single group' if len(active_groups) <= 1 else 'single channel'})")
        pipeline_result["steps"]["top_synthesis"] = {"status": "skipped", "reason": "single_group"}

    # ── Step 8: Template ──
    print("\n[8/9] FORMAT — Template selection...")
    template = classification["template"]
    pipeline_result["steps"]["format"] = {
        "template": template,
        "output_dir": str(DATA_PIPELINE),
    }

    # ── Step 9: Summary ──
    print("\n[9/9] MEMORY — Pipeline summary...")
    pipeline_result["status"] = "ready"
    pipeline_result["completed_at"] = datetime.now().isoformat()

    # Save full pipeline result
    result_file = DATA_PIPELINE / "pipeline_result.json"
    with open(result_file, "w") as f:
        json.dump(pipeline_result, f, indent=2, default=str)

    print(f"\n{'='*60}")
    print(f"Pipeline Status: {pipeline_result['status'].upper()}")
    print(f"{'='*60}")
    print(f"\nSub-agent prompts written to: {DATA_PIPELINE}/")
    print(f"Pipeline result saved to: {result_file}")

    if pipeline_result["status"] == "ready":
        print(f"\nNext steps:")
        print(f"  1. Invoke channel sub-agents (can run in parallel):")
        for ch in active_channels:
            print(f"     - {ch}: read {DATA_PIPELINE / f'{ch}_prompt.md'} and execute")
        print(f"  2. Collect outputs from {DATA_PIPELINE}/*_output.json")
        if group_synthesis_groups:
            print(f"  3. Invoke group synthesis agents (parallel across groups):")
            for g in group_synthesis_groups:
                print(f"     - {g}: read {DATA_PIPELINE / f'{g}_group_synthesis_prompt.md'}")
        print(f"  4. Invoke hypothesis sub-agent with all outputs")
        if needs_top_synthesis:
            print(f"  5. Invoke top-level synthesis with group outputs")
        print(f"  6. Format final report using {template}")

    return pipeline_result


def main():
    parser = argparse.ArgumentParser(
        description="Marketing Analytics Orchestrator — Run the full analysis pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_analysis.py "How did SEM perform last week?"
  python run_analysis.py "How is email performing?"
  python run_analysis.py "Compare all channels WoW"
  python run_analysis.py --channels sem,display,email
  python run_analysis.py --preprocess-only
  python run_analysis.py --skip-preprocess "SEM weekly review"
        """,
    )
    parser.add_argument("query", nargs="?", default="", help="Natural language analysis query")
    parser.add_argument("--channels", type=str,
                        help="Comma-separated channel list (e.g., sem,display,email,seo)")
    parser.add_argument("--period", type=str, help="Date range: YYYY-MM-DD/YYYY-MM-DD")
    parser.add_argument("--skip-preprocess", action="store_true", help="Skip preprocessing step")
    parser.add_argument("--preprocess-only", action="store_true", help="Only run preprocessing and validation")
    parser.add_argument("--dry-run", action="store_true", help="Don't write any files")
    parser.add_argument("--json", action="store_true", help="Output pipeline result as JSON")

    args = parser.parse_args()

    channels = args.channels.split(",") if args.channels else None

    if not args.query and not channels and not args.preprocess_only:
        parser.print_help()
        print("\nError: Provide a query or --channels or --preprocess-only")
        sys.exit(1)

    result = run_pipeline(
        query=args.query,
        channels=channels,
        period=args.period,
        skip_preprocess=args.skip_preprocess,
        preprocess_only=args.preprocess_only,
        dry_run=args.dry_run,
    )

    if args.json:
        print(json.dumps(result, indent=2, default=str))

    sys.exit(0 if result["status"] in ("ready", "preprocess_only") else 1)


if __name__ == "__main__":
    main()
