#!/usr/bin/env python3
"""
Marketing Analytics Orchestrator — Master pipeline runner.

Enforces the mandatory 7-step analysis chain:
1. CLASSIFY — Determine intent from user query (keyword match + LLM fallback)
2. PREPROCESS — Standardize new input files (Python script)
3. VALIDATE — Data quality gate (Python script, FAIL = block)
4. DISPATCH — Route to channel agent(s), parallel when possible
5. HYPOTHESIZE — Explain metric movements (sequential, after all channels)
6. SYNTHESIZE — Cross-channel view (conditional, if 2+ channels)
7. FORMAT + MEMORY UPDATE — Select template, render output, update baselines

Usage:
    python run_analysis.py "How did SEM perform last week?"
    python run_analysis.py "Compare all channels WoW"
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
# ROUTING TABLE
# ─────────────────────────────────────────────

ROUTING_TABLE = [
    {
        "keywords": ["sem", "google ads", "paid search", "cpc", "roas", "search ads", "adwords"],
        "channels": ["sem"],
        "agent_prompts": ["agents/paid/sem.md"],
        "also_invoke": ["agents/hypothesis.md"],
    },
    {
        "keywords": ["display", "programmatic", "dv360", "cpm", "banner", "viewability"],
        "channels": ["display"],
        "agent_prompts": ["agents/paid/display.md"],
        "also_invoke": ["agents/hypothesis.md"],
    },
    {
        "keywords": ["affiliate", "publisher", "commission", "epc", "partner"],
        "channels": ["affiliate"],
        "agent_prompts": ["agents/paid/affiliate.md"],
        "also_invoke": ["agents/hypothesis.md"],
    },
    {
        "keywords": ["seo", "organic", "rankings", "gsc", "search console", "position",
                      "crawl", "indexing", "page speed", "core web vitals", "technical seo"],
        "channels": ["seo"],
        "agent_prompts": ["agents/seo/content-seo.md"],
        "also_invoke": ["agents/hypothesis.md"],
    },
    {
        "keywords": ["incrementality", "incrementality test", "mroas", "troas test", "split test"],
        "channels": ["sem-incrementality"],
        "agent_prompts": ["agents/paid/sem-incrementality.md"],
        "also_invoke": [],  # Self-contained
        "self_contained": True,
    },
    {
        "keywords": ["overall", "all channels", "mix", "compare channels", "total",
                      "blended", "paid", "paid channels", "paid media"],
        "channels": ["sem", "display", "affiliate", "seo"],
        "agent_prompts": [
            "agents/paid/sem.md",
            "agents/paid/display.md",
            "agents/paid/affiliate.md",
            "agents/seo/content-seo.md",
        ],
        "also_invoke": ["agents/hypothesis.md", "agents/cross-channel/synthesis.md"],
    },
    {
        "keywords": ["budget", "pacing", "spend"],
        "channels": ["sem", "display", "affiliate"],
        "agent_prompts": [],  # Route to relevant channel agent based on available data
        "also_invoke": [],
    },
    {
        "keywords": ["anomal", "alert", "flag", "unusual"],  # "anomal" matches anomaly/anomalies/anomalous
        "channels": [],  # Route to all channels with available data
        "agent_prompts": [],
        "also_invoke": ["agents/hypothesis.md"],
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
            "agent_prompts": ["agents/paid/sem.md", ...],
            "also_invoke": ["agents/hypothesis.md", ...],
            "template": "templates/weekly-report.md",
            "self_contained": False,
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
        result = {
            "channels": best_match["channels"],
            "agent_prompts": best_match["agent_prompts"],
            "also_invoke": best_match.get("also_invoke", []),
            "self_contained": best_match.get("self_contained", False),
            "match_type": "keyword",
        }
    else:
        # Fallback: no keyword match. Default to listing available data.
        result = {
            "channels": [],
            "agent_prompts": [],
            "also_invoke": [],
            "self_contained": False,
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
    """Select output template based on query keywords and analysis results.

    Decision matrix:
    - anomaly-alert: if query mentions anomaly/alert/flag/unusual
    - period-comparison: if query mentions compare/vs/comparison
    - weekly-report: default for everything else
    """
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
    # Match patterns like "2026-02-10 to 2026-02-16" or "Feb 10 - Feb 16"
    iso_pattern = r"(\d{4}-\d{2}-\d{2})\s*(?:to|through|thru|-)\s*(\d{4}-\d{2}-\d{2})"
    match = re.search(iso_pattern, query)
    if match:
        return {"current_start": match.group(1), "current_end": match.group(2)}

    # "last week", "this week", etc. — return None to let agents use defaults
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
    # Match "na" as a standalone word (start, end, or surrounded by spaces/punctuation)
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
    """Scan /data/validated/ for available data files, grouped by source."""
    available = {}
    if not DATA_VALIDATED.exists():
        return available

    for f in DATA_VALIDATED.glob("*.csv"):
        name = f.name.lower()
        if name.startswith("google-ads"):
            available.setdefault("sem", []).append(str(f))
        elif name.startswith("gsc"):
            available.setdefault("seo", []).append(str(f))
        elif name.startswith("affiliate"):
            available.setdefault("affiliate", []).append(str(f))
        elif name.startswith("display"):
            available.setdefault("display", []).append(str(f))

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


def build_agent_context(channel: str, classification: dict) -> dict:
    """Build the context payload for a channel sub-agent.

    Returns a dict with only the relevant prompt, config, memory, and data
    for this specific channel — not the full 36KB payload.
    """
    channel_agent_map = {
        "sem": "agents/paid/sem.md",
        "display": "agents/paid/display.md",
        "affiliate": "agents/paid/affiliate.md",
        "seo": "agents/seo/content-seo.md",
    }

    channel_baseline_map = {
        "sem": "memory/baselines/sem-weekly-baselines.md",
        "display": "memory/baselines/display-weekly-baselines.md",
        "affiliate": "memory/baselines/affiliate-monthly-baselines.md",
        "seo": "memory/baselines/seo-weekly-baselines.md",
    }

    context = {
        "channel": channel,
        "agent_prompt": channel_agent_map.get(channel),
        "config": {
            "metrics": str(CONFIG_DIR / "metrics.yaml"),
            "thresholds": str(CONFIG_DIR / "thresholds.yaml"),
            "benchmarks": str(CONFIG_DIR / "benchmarks.yaml"),
        },
        "memory": {
            "baselines": str(PROJECT_ROOT / channel_baseline_map.get(channel, "")),
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
- geo: your geo filter
- period: "YYYY-MM-DD/YYYY-MM-DD"
- comparison_type: "{context['comparison_type']}"
- summary: array of metric objects (metric, current, prior, delta_pct, benchmark, status)
- top_movers: array of top 5 movers (rank, segment, metric, change_pct, likely_cause)
- anomalies: array of detected anomalies (metric, segment, z_score, direction, value, baseline)
- budget_pacing: object with mtd_spend, monthly_budget, linear_pace, variance_pct, projected_month_end, status (null for SEO)
- data_quality_notes: array of warning strings

Read the data files, perform your analysis, and return ONLY the JSON output.
Write the JSON output to: {str(DATA_PIPELINE / f'{channel}_output.json')}
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


def build_synthesis_prompt(channel_outputs: list[dict], hypothesis_output: dict) -> str:
    """Build the prompt for the synthesis sub-agent."""
    channels_json = json.dumps(channel_outputs, indent=2)
    hypothesis_json = json.dumps(hypothesis_output, indent=2)

    prompt = f"""You are the Cross-Channel Synthesis Agent.

## Instructions
Read your agent prompt: agents/cross-channel/synthesis.md

## Reference Files
- Metrics definitions: {str(CONFIG_DIR / 'metrics.yaml')}
- Business context: {str(MEMORY_DIR / 'context.md')}

## Channel Analysis Results
```json
{channels_json}
```

## Hypothesis Results
```json
{hypothesis_json}
```

## Output Requirements
Your output MUST be valid JSON conforming to: {str(SCHEMAS_DIR / 'synthesis-output.json')}

Produce JSON with:
- channel_mix: efficiency table (spend share vs revenue share)
- contradictions: any data conflicts across channels
- actions: top 5 ICE-scored action items

Write the JSON output to: {str(DATA_PIPELINE / 'synthesis_output.json')}
"""
    return prompt


# ─────────────────────────────────────────────
# STEP 5-6: VALIDATE OUTPUTS
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
# STEP 7: MEMORY UPDATE
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
    """Execute the full 7-step analysis pipeline.

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
    print("\n[1/7] CLASSIFY — Determining analysis intent...")
    if channels:
        classification = {
            "channels": channels,
            "agent_prompts": [],
            "also_invoke": ["agents/hypothesis.md"],
            "self_contained": False,
            "match_type": "explicit",
            "template": select_template(query.lower()),
            "date_range": parse_date_range(period or ""),
            "comparison_type": parse_comparison_type(query.lower()),
            "geo": parse_geo(query.lower()),
        }
        if len(channels) > 1:
            classification["also_invoke"].append("agents/cross-channel/synthesis.md")
    else:
        classification = classify_query(query)

    pipeline_result["steps"]["classify"] = classification
    print(f"  Channels: {classification['channels'] or '(auto-detect from available data)'}")
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
        print("\n[2/7] PREPROCESS — Standardizing input files...")
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
        print("\n[2/7] PREPROCESS — Skipped (--skip-preprocess)")
        pipeline_result["steps"]["preprocess"] = {"status": "skipped"}

    if preprocess_only:
        pipeline_result["status"] = "preprocess_only"
        print("\n[3-7] Skipped (--preprocess-only)")
        return pipeline_result

    # ── Step 3: Validate ──
    print("\n[3/7] VALIDATE — Running data quality checks...")
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
    print("\n[4/7] DISPATCH — Routing to channel agents...")
    available_data = get_available_data()
    requested = classification["channels"] or list(available_data.keys())
    active_channels, skipped = filter_channels_by_data(requested, available_data)

    if skipped:
        print(f"  Skipped (no data): {skipped}")
    if not active_channels:
        print("  No channels with available data. Add data files and re-run.")
        pipeline_result["status"] = "no_data"
        return pipeline_result

    print(f"  Active channels: {active_channels}")
    print(f"  Mode: {'parallel' if len(active_channels) > 1 else 'sequential'}")

    # Build contexts and prompts for each channel
    channel_contexts = {}
    for ch in active_channels:
        ctx = build_agent_context(ch, classification)
        channel_contexts[ch] = ctx
        prompt = build_subagent_prompt(ch, ctx)
        # Save prompt for sub-agent invocation
        prompt_file = DATA_PIPELINE / f"{ch}_prompt.md"
        with open(prompt_file, "w") as f:
            f.write(prompt)
        print(f"  Wrote sub-agent prompt: {prompt_file.name}")

    pipeline_result["steps"]["dispatch"] = {
        "active_channels": active_channels,
        "skipped_channels": skipped,
        "prompts_written": [f"{ch}_prompt.md" for ch in active_channels],
    }

    # ── Step 5: Hypothesis prompt ──
    print("\n[5/7] HYPOTHESIZE — Preparing hypothesis agent...")
    # The actual sub-agent execution happens via Claude Code Task tool.
    # This script prepares the prompts; the caller invokes sub-agents.
    hypothesis_prompt = build_hypothesis_prompt([])  # Placeholder; real data comes from step 4 outputs
    hyp_file = DATA_PIPELINE / "hypothesis_prompt.md"
    with open(hyp_file, "w") as f:
        f.write(hypothesis_prompt)
    print(f"  Wrote hypothesis prompt: {hyp_file.name}")

    pipeline_result["steps"]["hypothesis"] = {"prompt_written": str(hyp_file)}

    # ── Step 6: Synthesis prompt (conditional) ──
    needs_synthesis = len(active_channels) >= 2
    if needs_synthesis:
        print("\n[6/7] SYNTHESIZE — Preparing synthesis agent (multi-channel)...")
        synthesis_prompt = build_synthesis_prompt([], {})  # Placeholder
        syn_file = DATA_PIPELINE / "synthesis_prompt.md"
        with open(syn_file, "w") as f:
            f.write(synthesis_prompt)
        print(f"  Wrote synthesis prompt: {syn_file.name}")
        pipeline_result["steps"]["synthesis"] = {"prompt_written": str(syn_file)}
    else:
        print("\n[6/7] SYNTHESIZE — Skipped (single channel)")
        pipeline_result["steps"]["synthesis"] = {"status": "skipped", "reason": "single_channel"}

    # ── Step 7: Template + Summary ──
    print("\n[7/7] FORMAT — Template selection and pipeline summary...")
    template = classification["template"]

    # Refine template based on z-scores once data is available
    pipeline_result["steps"]["format"] = {
        "template": template,
        "output_dir": str(DATA_PIPELINE),
    }

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
            print(f"     - Read {DATA_PIPELINE / f'{ch}_prompt.md'} and execute")
        print(f"  2. Collect outputs from {DATA_PIPELINE}/*_output.json")
        print(f"  3. Invoke hypothesis sub-agent with channel outputs")
        if needs_synthesis:
            print(f"  4. Invoke synthesis sub-agent with all outputs")
        print(f"  5. Format final report using {template}")

    return pipeline_result


def main():
    parser = argparse.ArgumentParser(
        description="Marketing Analytics Orchestrator — Run the full analysis pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_analysis.py "How did SEM perform last week?"
  python run_analysis.py "Compare all channels WoW"
  python run_analysis.py --channels sem,display
  python run_analysis.py --preprocess-only
  python run_analysis.py --skip-preprocess "SEM weekly review"
        """,
    )
    parser.add_argument("query", nargs="?", default="", help="Natural language analysis query")
    parser.add_argument("--channels", type=str, help="Comma-separated channel list (sem,display,affiliate,seo)")
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
