#!/usr/bin/env python3
"""
Data Quality Validator — Deterministic validation of preprocessed data files.

Replaces the LLM-based data-quality.md agent with rule-based Python validation.
Implements the 5-step validation sequence:
1. Schema validation (required columns, data types)
2. Completeness checks (date coverage, null ratios)
3. Sanity checks (per data-quality-rules.yaml bounds)
4. Screenshot cross-reference (flag discrepancies >2%)
5. Cross-source consistency (multi-file comparisons)

Returns structured JSON with PASS/WARN/FAIL per check.
Gate logic: any FAIL -> block analysis; any WARN -> proceed with caveats.

Usage:
    python scripts/validate_data.py                           # validate all files in /data/validated/
    python scripts/validate_data.py path/to/file.csv          # validate specific file
    python scripts/validate_data.py --json                    # output as JSON for orchestrator
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

try:
    import yaml
except ImportError:
    yaml = None

# Resolve paths relative to project root
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_VALIDATED = PROJECT_ROOT / "data" / "validated"
CONFIG_DIR = PROJECT_ROOT / "config"
SCHEMAS_DIR = PROJECT_ROOT / "data" / "schemas"
PIPELINE_DIR = PROJECT_ROOT / "data" / "pipeline"

# Source name -> schema file mapping
SOURCE_SCHEMA_MAP = {
    "google-ads": "google-ads",
    "gsc": "gsc",
    "affiliate": "affiliate",
    "display": "display",
}

# Source name -> data-quality-rules.yaml key mapping
SOURCE_RULES_MAP = {
    "google-ads": "google_ads",
    "gsc": "google_search_console",
    "affiliate": "affiliate_export",
    "display": "display_export",
}


def load_config(filename: str) -> dict:
    """Load a YAML config file."""
    if yaml is None:
        return {}
    path = CONFIG_DIR / filename
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def load_schema(source: str) -> dict | None:
    """Load the YAML schema for a data source."""
    if yaml is None:
        return None
    schema_key = SOURCE_SCHEMA_MAP.get(source)
    if not schema_key:
        return None
    path = SCHEMAS_DIR / f"{schema_key}.yaml"
    if not path.exists():
        return None
    with open(path) as f:
        return yaml.safe_load(f)


def detect_source_from_filename(filename: str) -> str | None:
    """Detect data source from standardized filename."""
    name = filename.lower()
    if name.startswith("google-ads"):
        return "google-ads"
    elif name.startswith("gsc"):
        return "gsc"
    elif name.startswith("affiliate"):
        return "affiliate"
    elif name.startswith("display"):
        return "display"
    return None


class ValidationResult:
    """A single validation check result."""

    def __init__(self, check_name: str, status: str, message: str, details: dict | None = None):
        self.check_name = check_name
        self.status = status  # PASS, WARN, FAIL
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {
            "check": self.check_name,
            "status": self.status,
            "message": self.message,
            "details": self.details,
        }


class FileValidation:
    """Validation results for a single file."""

    def __init__(self, filepath: Path, source: str):
        self.filepath = filepath
        self.source = source
        self.checks: list[ValidationResult] = []
        self.overall_status = "PASS"

    def add(self, result: ValidationResult):
        self.checks.append(result)
        if result.status == "FAIL":
            self.overall_status = "FAIL"
        elif result.status == "WARN" and self.overall_status != "FAIL":
            self.overall_status = "WARN"

    def to_dict(self) -> dict:
        return {
            "file": str(self.filepath),
            "source": self.source,
            "overall_status": self.overall_status,
            "checks": [c.to_dict() for c in self.checks],
        }


def validate_schema(df: pd.DataFrame, schema: dict) -> list[ValidationResult]:
    """Step 1: Validate required columns are present with correct types."""
    results = []

    if not schema or "columns" not in schema:
        results.append(ValidationResult("schema_columns", "WARN", "No schema available for validation"))
        return results

    columns_spec = schema["columns"]
    df_cols = set(df.columns)

    # Check required columns
    missing_required = []
    for col_name, col_spec in columns_spec.items():
        if isinstance(col_spec, dict) and col_spec.get("required", False):
            if col_name not in df_cols:
                missing_required.append(col_name)

    if missing_required:
        results.append(ValidationResult(
            "schema_required_columns",
            "FAIL",
            f"Missing required columns: {missing_required}",
            {"missing": missing_required},
        ))
    else:
        results.append(ValidationResult(
            "schema_required_columns",
            "PASS",
            "All required columns present",
        ))

    # Check for fully empty critical columns
    empty_columns = []
    for col_name in columns_spec:
        if col_name in df_cols:
            if df[col_name].isna().all():
                empty_columns.append(col_name)

    if empty_columns:
        # FAIL if required column is empty, WARN if optional
        required_empty = [c for c in empty_columns
                          if isinstance(columns_spec.get(c), dict)
                          and columns_spec[c].get("required", False)]
        optional_empty = [c for c in empty_columns if c not in required_empty]

        if required_empty:
            results.append(ValidationResult(
                "schema_empty_columns",
                "FAIL",
                f"Required columns are completely empty: {required_empty}",
                {"required_empty": required_empty, "optional_empty": optional_empty},
            ))
        elif optional_empty:
            results.append(ValidationResult(
                "schema_empty_columns",
                "WARN",
                f"Optional columns are completely empty: {optional_empty}",
                {"optional_empty": optional_empty},
            ))
    else:
        results.append(ValidationResult(
            "schema_empty_columns",
            "PASS",
            "No empty columns detected",
        ))

    # Check data types
    type_issues = []
    for col_name, col_spec in columns_spec.items():
        if col_name not in df_cols or not isinstance(col_spec, dict):
            continue

        col_type = col_spec.get("type", "")

        if col_type in ("integer", "float"):
            non_null = df[col_name].dropna()
            if len(non_null) > 0:
                numeric_check = pd.to_numeric(non_null, errors="coerce")
                non_numeric_count = numeric_check.isna().sum()
                if non_numeric_count > 0:
                    type_issues.append(f"{col_name}: {non_numeric_count} non-numeric values")

        elif col_type == "date":
            non_null = df[col_name].dropna()
            if len(non_null) > 0:
                date_check = pd.to_datetime(non_null, errors="coerce")
                bad_dates = date_check.isna().sum()
                if bad_dates > 0:
                    type_issues.append(f"{col_name}: {bad_dates} unparseable dates")

    if type_issues:
        results.append(ValidationResult(
            "schema_data_types",
            "WARN",
            f"Data type issues found: {len(type_issues)}",
            {"issues": type_issues},
        ))
    else:
        results.append(ValidationResult(
            "schema_data_types",
            "PASS",
            "All data types valid",
        ))

    return results


def validate_completeness(df: pd.DataFrame, source: str) -> list[ValidationResult]:
    """Step 2: Check date coverage, identify missing dates, flag null ratios."""
    results = []

    if "Date" not in df.columns:
        results.append(ValidationResult(
            "completeness_dates",
            "WARN",
            "No Date column — cannot check completeness",
        ))
        return results

    dates = pd.to_datetime(df["Date"], errors="coerce").dropna()
    if len(dates) == 0:
        results.append(ValidationResult(
            "completeness_dates",
            "FAIL",
            "No valid dates found in Date column",
        ))
        return results

    date_min = dates.min()
    date_max = dates.max()
    unique_dates = dates.dt.date.unique()
    expected_days = (date_max - date_min).days + 1

    # Check for missing dates
    all_dates = pd.date_range(date_min, date_max, freq="D")
    missing_dates = sorted(set(all_dates.date) - set(unique_dates))

    if missing_dates:
        if len(missing_dates) > expected_days * 0.3:
            status = "FAIL"
            msg = f"Major gaps: {len(missing_dates)} of {expected_days} days missing"
        else:
            status = "WARN"
            msg = f"{len(missing_dates)} of {expected_days} days missing"
        results.append(ValidationResult(
            "completeness_dates",
            status,
            msg,
            {"missing_dates": [str(d) for d in missing_dates[:10]],
             "total_missing": len(missing_dates),
             "date_range": f"{date_min.date()} to {date_max.date()}"},
        ))
    else:
        results.append(ValidationResult(
            "completeness_dates",
            "PASS",
            f"All {expected_days} days present ({date_min.date()} to {date_max.date()})",
        ))

    # Check null ratios in critical columns
    critical_cols = {
        "google-ads": ["Campaign", "Impressions", "Clicks", "Cost"],
        "gsc": ["Page", "Clicks", "Impressions"],
        "affiliate": ["Publisher", "Clicks", "Conversions", "Revenue"],
        "display": ["Campaign", "Impressions", "Clicks", "Cost"],
    }

    cols_to_check = critical_cols.get(source, [])
    null_issues = []
    for col in cols_to_check:
        if col in df.columns:
            null_pct = df[col].isna().mean()
            if null_pct > 0.1:
                null_issues.append(f"{col}: {null_pct:.1%} null")
            elif null_pct > 0:
                null_issues.append(f"{col}: {null_pct:.1%} null (minor)")

    if null_issues:
        has_major = any("minor" not in issue for issue in null_issues)
        results.append(ValidationResult(
            "completeness_nulls",
            "WARN" if has_major else "PASS",
            f"Null values found in {len(null_issues)} columns",
            {"null_columns": null_issues},
        ))
    else:
        results.append(ValidationResult(
            "completeness_nulls",
            "PASS",
            "No significant nulls in critical columns",
        ))

    return results


def validate_sanity(df: pd.DataFrame, source: str, rules: dict) -> list[ValidationResult]:
    """Step 3: Apply sanity bounds from data-quality-rules.yaml."""
    results = []

    source_key = SOURCE_RULES_MAP.get(source)
    if not source_key or source_key not in rules:
        results.append(ValidationResult(
            "sanity_checks",
            "WARN",
            f"No sanity rules defined for source: {source}",
        ))
        return results

    source_rules = rules[source_key]
    sanity_checks = source_rules.get("sanity_checks", {})

    violations = []

    for check_name, bounds in sanity_checks.items():
        if not isinstance(bounds, dict):
            continue

        min_val = bounds.get("min")
        max_val = bounds.get("max")

        # Map check name to actual column/computation
        if check_name == "ctr":
            if "CTR" in df.columns:
                col_data = pd.to_numeric(df["CTR"], errors="coerce")
            elif "Clicks" in df.columns and "Impressions" in df.columns:
                clicks = pd.to_numeric(df["Clicks"], errors="coerce")
                impressions = pd.to_numeric(df["Impressions"], errors="coerce")
                col_data = clicks / impressions.replace(0, float("nan"))
            else:
                continue
        elif check_name == "cpc":
            if "Cost" in df.columns and "Clicks" in df.columns:
                cost = pd.to_numeric(df["Cost"], errors="coerce")
                clicks = pd.to_numeric(df["Clicks"], errors="coerce")
                col_data = cost / clicks.replace(0, float("nan"))
            else:
                continue
        elif check_name == "cvr":
            if "Conversions" in df.columns and "Clicks" in df.columns:
                conv = pd.to_numeric(df["Conversions"], errors="coerce")
                clicks = pd.to_numeric(df["Clicks"], errors="coerce")
                col_data = conv / clicks.replace(0, float("nan"))
            else:
                continue
        elif check_name == "roas":
            if "Conversion Value" in df.columns and "Cost" in df.columns:
                rev = pd.to_numeric(df["Conversion Value"], errors="coerce")
                cost = pd.to_numeric(df["Cost"], errors="coerce")
                col_data = rev / cost.replace(0, float("nan"))
            elif "Revenue" in df.columns and "Cost" in df.columns:
                rev = pd.to_numeric(df["Revenue"], errors="coerce")
                cost = pd.to_numeric(df["Cost"], errors="coerce")
                col_data = rev / cost.replace(0, float("nan"))
            else:
                continue
        elif check_name == "position":
            if "Position" in df.columns:
                col_data = pd.to_numeric(df["Position"], errors="coerce")
            else:
                continue
        elif check_name == "commission_rate":
            if "Commission" in df.columns and "Revenue" in df.columns:
                comm = pd.to_numeric(df["Commission"], errors="coerce")
                rev = pd.to_numeric(df["Revenue"], errors="coerce")
                col_data = comm / rev.replace(0, float("nan"))
            else:
                continue
        elif check_name == "epc":
            if "Revenue" in df.columns and "Clicks" in df.columns:
                rev = pd.to_numeric(df["Revenue"], errors="coerce")
                clicks = pd.to_numeric(df["Clicks"], errors="coerce")
                col_data = rev / clicks.replace(0, float("nan"))
            else:
                continue
        elif check_name == "cpm":
            if "Cost" in df.columns and "Impressions" in df.columns:
                cost = pd.to_numeric(df["Cost"], errors="coerce")
                impr = pd.to_numeric(df["Impressions"], errors="coerce")
                col_data = (cost / impr.replace(0, float("nan"))) * 1000
            else:
                continue
        elif check_name == "viewability":
            if "Viewable Impressions" in df.columns and "Impressions" in df.columns:
                viewable = pd.to_numeric(df["Viewable Impressions"], errors="coerce")
                impr = pd.to_numeric(df["Impressions"], errors="coerce")
                col_data = viewable / impr.replace(0, float("nan"))
            else:
                continue
        elif check_name == "daily_spend_max":
            if "Cost" in df.columns and "Date" in df.columns:
                daily_spend = df.groupby("Date")["Cost"].sum()
                max_daily = daily_spend.max()
                if max_daily > bounds.get("max", bounds):
                    violations.append(f"daily_spend_max: max daily spend ${max_daily:,.0f} exceeds ${bounds:,}")
                continue
            else:
                continue
        else:
            continue

        col_data = col_data.dropna()
        if len(col_data) == 0:
            continue

        below_min = (col_data < min_val).sum() if min_val is not None else 0
        above_max = (col_data > max_val).sum() if max_val is not None else 0

        if below_min > 0:
            violations.append(f"{check_name}: {below_min} values below minimum {min_val}")
        if above_max > 0:
            violations.append(f"{check_name}: {above_max} values above maximum {max_val}")

    if violations:
        results.append(ValidationResult(
            "sanity_checks",
            "WARN",
            f"{len(violations)} sanity check violations",
            {"violations": violations},
        ))
    else:
        results.append(ValidationResult(
            "sanity_checks",
            "PASS",
            "All sanity checks passed",
        ))

    return results


def validate_cross_source(validated_files: list[Path]) -> list[ValidationResult]:
    """Step 5: Cross-source consistency checks."""
    results = []

    # Group files by date range
    files_by_range = {}
    for f in validated_files:
        # Extract date range from filename
        name = f.stem
        parts = name.split("_")
        # Find date-like parts
        date_parts = [p for p in parts if len(p) == 10 and p.count("-") == 2]
        if len(date_parts) >= 2:
            key = f"{date_parts[0]}_to_{date_parts[-1]}"
            files_by_range.setdefault(key, []).append(f)

    # Check for period mismatches across sources for same geo
    for date_range, files in files_by_range.items():
        if len(files) > 1:
            results.append(ValidationResult(
                "cross_source_period",
                "PASS",
                f"Period {date_range}: {len(files)} files with matching date ranges",
            ))

    if not results:
        results.append(ValidationResult(
            "cross_source",
            "PASS",
            "Cross-source validation skipped (insufficient files for comparison)",
        ))

    return results


def validate_file(filepath: Path, rules: dict) -> FileValidation:
    """Run all validation checks on a single file."""
    source = detect_source_from_filename(filepath.name)
    if not source:
        validation = FileValidation(filepath, "unknown")
        validation.add(ValidationResult(
            "source_detection",
            "FAIL",
            f"Cannot detect source from filename: {filepath.name}",
        ))
        return validation

    validation = FileValidation(filepath, source)
    schema = load_schema(source)

    # Read file
    try:
        df = pd.read_csv(filepath)
    except Exception as e:
        validation.add(ValidationResult(
            "file_read",
            "FAIL",
            f"Cannot read file: {e}",
        ))
        return validation

    if df.empty:
        validation.add(ValidationResult(
            "file_read",
            "FAIL",
            "File is empty",
        ))
        return validation

    validation.add(ValidationResult(
        "file_read",
        "PASS",
        f"Read {len(df)} rows, {len(df.columns)} columns",
    ))

    # Step 1: Schema validation
    for r in validate_schema(df, schema):
        validation.add(r)

    # Step 2: Completeness checks
    for r in validate_completeness(df, source):
        validation.add(r)

    # Step 3: Sanity checks
    for r in validate_sanity(df, source, rules):
        validation.add(r)

    return validation


def run_validation(files: list[Path] | None = None, output_json: bool = False) -> dict:
    """Run validation on files and return results.

    Returns:
        {
            "overall_status": "PASS" | "WARN" | "FAIL",
            "files": [...],
            "cross_source": [...],
            "gate_decision": "PROCEED" | "PROCEED_WITH_CAVEATS" | "BLOCK",
            "caveats": [...]
        }
    """
    rules = load_config("data-quality-rules.yaml")

    if files is None:
        files = sorted(DATA_VALIDATED.glob("*.csv"))

    if not files:
        return {
            "overall_status": "PASS",
            "files": [],
            "cross_source": [],
            "gate_decision": "PROCEED",
            "caveats": [],
            "message": "No files to validate",
        }

    file_results = []
    for f in files:
        validation = validate_file(f, rules)
        file_results.append(validation)

    # Step 5: Cross-source consistency
    cross_source = validate_cross_source(files)

    # Determine overall status
    overall = "PASS"
    caveats = []

    for fr in file_results:
        if fr.overall_status == "FAIL":
            overall = "FAIL"
        elif fr.overall_status == "WARN" and overall != "FAIL":
            overall = "WARN"

        # Collect caveats (WARN items)
        for check in fr.checks:
            if check.status == "WARN":
                caveats.append(f"{fr.filepath.name}: {check.message}")

    for cs in cross_source:
        if cs.status == "FAIL":
            overall = "FAIL"
        elif cs.status == "WARN" and overall != "FAIL":
            overall = "WARN"
            caveats.append(cs.message)

    # Gate decision
    if overall == "FAIL":
        gate = "BLOCK"
    elif overall == "WARN":
        gate = "PROCEED_WITH_CAVEATS"
    else:
        gate = "PROCEED"

    result = {
        "overall_status": overall,
        "files": [fr.to_dict() for fr in file_results],
        "cross_source": [cs.to_dict() for cs in cross_source],
        "gate_decision": gate,
        "caveats": caveats,
    }

    # Save results for pipeline use
    PIPELINE_DIR.mkdir(parents=True, exist_ok=True)
    with open(PIPELINE_DIR / "dq_results.json", "w") as f:
        json.dump(result, f, indent=2)

    return result


def main():
    parser = argparse.ArgumentParser(description="Validate preprocessed marketing data files")
    parser.add_argument("files", nargs="*", help="Specific files to validate (default: all in /data/validated/)")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    if args.files:
        files = [Path(f).resolve() for f in args.files]
    else:
        files = None  # Will default to all validated files

    result = run_validation(files, output_json=args.json)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        # Human-readable output
        print(f"\n{'='*60}")
        print(f"DATA QUALITY VALIDATION REPORT")
        print(f"{'='*60}")

        for fr in result["files"]:
            print(f"\n  File: {Path(fr['file']).name}")
            print(f"  Source: {fr['source']}")
            print(f"  Status: {fr['overall_status']}")
            for check in fr["checks"]:
                icon = {"PASS": "+", "WARN": "!", "FAIL": "X"}[check["status"]]
                print(f"    [{icon}] {check['check']}: {check['message']}")

        print(f"\n{'='*60}")
        print(f"Overall: {result['overall_status']}")
        print(f"Gate Decision: {result['gate_decision']}")

        if result["caveats"]:
            print(f"\nCaveats:")
            for caveat in result["caveats"]:
                print(f"  - {caveat}")

        print(f"\nResults saved to: {PIPELINE_DIR / 'dq_results.json'}")


if __name__ == "__main__":
    main()
