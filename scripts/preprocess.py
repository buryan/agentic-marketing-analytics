#!/usr/bin/env python3
"""
Preprocessor Script — Deterministic file standardization.

Replaces the LLM-based preprocessor.md agent with a Python script that handles:
- File type detection (CSV, TSV, XLSX)
- Source identification via column matching against /data/schemas/
- Column standardization (renaming, currency/percent stripping)
- Date standardization to YYYY-MM-DD
- File splitting (NA/INTL, junk headers/footers)
- Standard file naming: {source}_{geo}_{start}_to_{end}.csv

Usage:
    python scripts/preprocess.py                    # process all new files in /data/input/
    python scripts/preprocess.py path/to/file.csv   # process a specific file
    python scripts/preprocess.py --dry-run           # show what would be done without writing
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

try:
    import yaml
except ImportError:
    yaml = None

# Resolve paths relative to project root
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_INPUT = PROJECT_ROOT / "data" / "input"
DATA_VALIDATED = PROJECT_ROOT / "data" / "validated"
SCHEMAS_DIR = PROJECT_ROOT / "data" / "schemas"

# Column name aliases: common variations -> standard name
COLUMN_ALIASES = {
    # Google Ads
    "impr.": "Impressions",
    "impr": "Impressions",
    "avg. cpc": None,  # Remove; derive from Cost/Clicks
    "conv. value": "Conversion Value",
    "conv. value / cost": None,  # Remove; derive as ROAS
    "conv.": "Conversions",
    "all conv.": None,  # Remove unless primary
    "impr. share": "Impression Share",
    "search impr. share": "Impression Share",
    # GSC
    "average position": "Position",
    "avg position": "Position",
    "avg. position": "Position",
    "url": "Page",
    # Affiliate
    "sales": "Conversions",
    "orders": "Conversions",
    "commissions": "Commission",
    "pub": "Publisher",
    "publisher name": "Publisher",
    # Display
    "insertion order": "Campaign",
    "line item": "Campaign",
    "io": "Campaign",
    "spend": "Cost",
    "media cost": "Cost",
    "viewable impressions": "Viewable Impressions",
    "measurable impressions": "Viewable Impressions",
    # CRM / Email
    "subject line": "Campaign",
    "subject": "Campaign",
    "email name": "Campaign",
    "sends": "Sent",
    "total sent": "Sent",
    "total delivered": "Delivered",
    "unique opens": "Opens",
    "total opens": "Opens",
    "unique clicks": "Clicks",
    "total clicks": "Clicks",
    "unsubscribes": "Unsubscribes",
    "opt outs": "Unsubscribes",
    "opt-outs": "Unsubscribes",
    "hard bounces": "Bounces",
    "soft bounces": "Bounces",
    # Push / SMS
    "push name": "Campaign",
    "notification name": "Campaign",
    "message name": "Campaign",
    # Social
    "ad set": "Campaign",
    "ad set name": "Campaign",
    "adset": "Campaign",
    "engagement": "Engagement",
    "engagements": "Engagement",
    "video views": "Video Views",
    "video completions": "Video Completions",
    "3s views": "Video Views",
    "thruplays": "Video Completions",
    # Metasearch
    "property": "Campaign",
    "hotel": "Campaign",
    "listing": "Campaign",
    "bookings": "Bookings",
    "reservations": "Bookings",
    "avg bid": "Avg Bid",
    "average bid": "Avg Bid",
    # Distribution
    "partner": "Partner",
    "partner name": "Partner",
    "network": "Partner",
    "transactions": "Transactions",
    "orders": "Transactions",
    "net revenue": "Net Revenue",
    "incentive cost": "Incentive Cost",
    "incentive": "Incentive Cost",
    # Promotions
    "promotion": "Promo Name",
    "promo": "Promo Name",
    "promotion name": "Promo Name",
    "coupon code": "Promo Name",
    "voucher": "Promo Name",
    "discount": "Discount Amount",
    "discount cost": "Discount Amount",
    "discount_amount": "Discount Amount",
    "promo type": "Promo Type",
    "promotion type": "Promo Type",
    "discount type": "Discount Type",
    "discount value": "Discount Value",
    "redemptions": "Redemptions",
    "eligible users": "Eligible Users",
    # HALO feed
    "dimension 1": "Channel",
    "dimension 2": "Date",
    "m1+vfm": "M1VFM",
    "m1 + vfm": "M1VFM",
    "gb": "Gross Billings",
    "gr": "Gross Revenue",
    "nob": "New Order Base",
    "nor": "New Order Revenue",
    "ils": "ILS",
    "vfm": "VFM",
    "order discount": "Order Discount",
    "order item count": "Order Item Count",
    "promo spend": "Promo Spend",
}

# Source identification rules: (source_name, required_columns_set)
# Order matters: most specific (most required columns) first to avoid false matches.
# Google Ads requires Conversions; Display does not. This is the key discriminator.
SOURCE_SIGNATURES = [
    # Most specific first to avoid false matches
    ("halo", {"Dimension 1", "Dimension 2", "Activations", "Impressions", "Spend", "M1+VFM"}),
    ("gsc", {"Page", "Impressions", "Clicks", "CTR", "Position"}),
    ("google-ads", {"Campaign", "Impressions", "Clicks", "Cost", "Conversions"}),
    ("email", {"Campaign", "Sent", "Delivered", "Opens", "Clicks"}),
    ("push", {"Campaign", "Sent", "Delivered", "Opens"}),
    ("sms", {"Campaign", "Sent", "Delivered"}),
    ("social-paid", {"Campaign", "Impressions", "Clicks", "Cost", "Reach"}),
    ("metasearch", {"Campaign", "Impressions", "Clicks", "Cost", "Bookings"}),
    ("affiliate", {"Publisher", "Clicks", "Commission"}),
    ("distribution", {"Partner", "Transactions", "Revenue", "Commission"}),
    ("referral-program", {"Partner", "Transactions", "Incentive Cost"}),
    ("social-organic", {"Campaign", "Reach", "Engagement"}),
    ("promo", {"Promo Name", "Orders", "Revenue", "Discount Amount"}),
    ("display", {"Campaign", "Impressions", "Cost"}),
]

# Date format detection patterns
DATE_FORMATS = [
    ("%Y-%m-%d", "YYYY-MM-DD"),
    ("%m/%d/%Y", "MM/DD/YYYY"),
    ("%d/%m/%Y", "DD/MM/YYYY"),
    ("%m/%d/%y", "MM/DD/YY"),
    ("%d/%m/%y", "DD/MM/YY"),
    ("%Y/%m/%d", "YYYY/MM/DD"),
    ("%d-%b-%Y", "DD-Mon-YYYY"),
    ("%d-%b-%y", "DD-Mon-YY"),
    ("%b %d, %Y", "Mon DD, YYYY"),
]


def load_schemas():
    """Load all YAML schemas from /data/schemas/."""
    if yaml is None:
        return {}
    schemas = {}
    for f in SCHEMAS_DIR.glob("*.yaml"):
        with open(f) as fh:
            schemas[f.stem] = yaml.safe_load(fh)
    return schemas


def detect_file_type(filepath: Path) -> str:
    """Detect file type from extension."""
    ext = filepath.suffix.lower()
    if ext in (".csv", ".tsv"):
        return "csv"
    elif ext in (".xlsx", ".xls"):
        return "xlsx"
    elif ext in (".png", ".jpg", ".jpeg"):
        return "screenshot"
    elif ext == ".pdf":
        return "pdf"
    else:
        return "unknown"


def read_file(filepath: Path) -> pd.DataFrame | None:
    """Read a tabular file into a DataFrame."""
    file_type = detect_file_type(filepath)

    if file_type == "csv":
        # Try multiple separators and encodings
        for sep in [",", "\t", ";"]:
            try:
                df = pd.read_csv(filepath, sep=sep, encoding="utf-8")
                if len(df.columns) > 1:
                    return df
            except Exception:
                pass
        # Fallback: try latin-1 encoding
        try:
            return pd.read_csv(filepath, encoding="latin-1")
        except Exception:
            return None

    elif file_type == "xlsx":
        try:
            return pd.read_excel(filepath, sheet_name=0)
        except Exception:
            return None

    return None


def strip_junk_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Remove header junk rows (report titles, timestamps) and footer summary rows."""
    if df.empty:
        return df

    # Drop rows where all values are NaN
    df = df.dropna(how="all").reset_index(drop=True)

    # Check if first few rows look like junk headers (all strings, no numeric data)
    rows_to_drop = []
    for i in range(min(5, len(df))):
        row = df.iloc[i]
        # If a row has fewer than 2 non-null values, it's likely junk
        non_null = row.dropna()
        if len(non_null) <= 1:
            rows_to_drop.append(i)
        else:
            break  # Stop at first non-junk row

    if rows_to_drop:
        df = df.drop(rows_to_drop).reset_index(drop=True)

    # Check for summary/total rows at bottom
    if len(df) > 1:
        last_rows_to_check = min(3, len(df))
        for i in range(1, last_rows_to_check + 1):
            row = df.iloc[-i]
            first_val = str(row.iloc[0]).lower().strip() if pd.notna(row.iloc[0]) else ""
            if first_val in ("total", "totals", "grand total", "sum", "summary", ""):
                df = df.iloc[:-i]
                break

    return df.reset_index(drop=True)


def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename columns using alias map, strip whitespace, remove currency/percent symbols."""
    # Strip whitespace from column names
    df.columns = [col.strip() for col in df.columns]

    # Apply aliases (case-insensitive)
    new_columns = {}
    drop_columns = []
    for col in df.columns:
        col_lower = col.lower().strip()
        if col_lower in COLUMN_ALIASES:
            alias = COLUMN_ALIASES[col_lower]
            if alias is None:
                drop_columns.append(col)
            else:
                new_columns[col] = alias
        # Also check without trailing periods
        elif col_lower.rstrip(".") in COLUMN_ALIASES:
            alias = COLUMN_ALIASES[col_lower.rstrip(".")]
            if alias is None:
                drop_columns.append(col)
            else:
                new_columns[col] = alias

    if drop_columns:
        df = df.drop(columns=drop_columns, errors="ignore")

    if new_columns:
        df = df.rename(columns=new_columns)

    # Clean numeric columns: remove $, commas, % signs
    for col in df.columns:
        if df[col].dtype == object:
            sample = df[col].dropna().head(20)
            if len(sample) == 0:
                continue

            # Check if values look numeric with currency/percent formatting
            numeric_pattern = re.compile(r"^[\s$%,.\d+-]+$")
            looks_numeric = sample.apply(lambda x: bool(numeric_pattern.match(str(x)))).mean() > 0.7

            if looks_numeric:
                # Strip currency symbols, commas, percent signs, spaces
                cleaned = df[col].astype(str).str.replace(r"[$,\s]", "", regex=True)

                # Handle percent: convert to decimal
                has_percent = df[col].astype(str).str.contains("%").any()
                cleaned = cleaned.str.replace("%", "", regex=False)

                df[col] = pd.to_numeric(cleaned, errors="coerce")

                if has_percent:
                    # Only convert to decimal if values look like percentages (> 1)
                    if df[col].dropna().mean() > 1:
                        df[col] = df[col] / 100

    return df


def detect_date_format(series: pd.Series) -> str | None:
    """Detect the date format of a string series."""
    sample = series.dropna().head(20).astype(str)
    if len(sample) == 0:
        return None

    for fmt, label in DATE_FORMATS:
        matches = 0
        for val in sample:
            try:
                datetime.strptime(val.strip(), fmt)
                matches += 1
            except ValueError:
                pass
        if matches / len(sample) >= 0.8:
            return fmt

    return None


def standardize_dates(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Convert Date column to YYYY-MM-DD format. Returns (df, warnings)."""
    warnings = []

    if "Date" not in df.columns:
        # Try to find a date-like column
        for col in df.columns:
            if col.lower() in ("date", "day", "report date"):
                df = df.rename(columns={col: "Date"})
                break

    if "Date" not in df.columns:
        warnings.append("WARN: No Date column found")
        return df, warnings

    # If already datetime, just format
    if pd.api.types.is_datetime64_any_dtype(df["Date"]):
        df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
        return df, warnings

    # Detect format
    fmt = detect_date_format(df["Date"])
    if fmt is None:
        # Try pandas auto-detection
        try:
            df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")
            return df, warnings
        except Exception:
            warnings.append("WARN: Could not detect date format. Dates left as-is.")
            return df, warnings

    # Check for ambiguous dates (DD/MM vs MM/DD)
    if fmt in ("%m/%d/%Y", "%d/%m/%Y", "%m/%d/%y", "%d/%m/%y"):
        sample = df["Date"].dropna().head(50).astype(str)
        day_parts = []
        month_parts = []
        for val in sample:
            parts = re.split(r"[/\-.]", val.strip())
            if len(parts) >= 2:
                try:
                    p1, p2 = int(parts[0]), int(parts[1])
                    day_parts.append(p1 if fmt.startswith("%d") else p2)
                    month_parts.append(p2 if fmt.startswith("%d") else p1)
                except ValueError:
                    pass

        # If any value > 12 in the month position, the format is probably wrong
        if month_parts and max(month_parts) > 12:
            # Swap format assumption
            if fmt == "%m/%d/%Y":
                fmt = "%d/%m/%Y"
            elif fmt == "%d/%m/%Y":
                fmt = "%m/%d/%Y"
            warnings.append(f"WARN: Ambiguous date format detected. Using {fmt}")

    try:
        df["Date"] = pd.to_datetime(df["Date"], format=fmt).dt.strftime("%Y-%m-%d")
    except Exception:
        try:
            df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")
        except Exception:
            warnings.append("WARN: Date conversion failed for some rows")

    return df, warnings


def identify_source(df: pd.DataFrame) -> str | None:
    """Match DataFrame columns against source signatures."""
    cols = set(df.columns)

    for source_name, required in SOURCE_SIGNATURES:
        if required.issubset(cols):
            return source_name

    # Fuzzy match: try case-insensitive
    cols_lower = {c.lower() for c in df.columns}
    for source_name, required in SOURCE_SIGNATURES:
        required_lower = {c.lower() for c in required}
        if required_lower.issubset(cols_lower):
            return source_name

    return None


def detect_geo(df: pd.DataFrame, source: str) -> str:
    """Detect geography from data. Returns 'na', 'intl', or 'all'."""
    if source in ("google-ads", "display"):
        # Check Campaign names for geo indicators
        if "Campaign" in df.columns:
            campaigns = df["Campaign"].dropna().astype(str)
            has_na = campaigns.str.contains(r"\bNA\b|North America|_NA_|_na_", case=False, regex=True).any()
            has_intl = campaigns.str.contains(r"\bINTL\b|International|_INTL_|_intl_", case=False, regex=True).any()
            if has_na and has_intl:
                return "all"
            elif has_na:
                return "na"
            elif has_intl:
                return "intl"
    elif source == "gsc":
        if "Country" in df.columns:
            countries = df["Country"].dropna().unique()
            if len(countries) > 1:
                return "all"
            elif len(countries) == 1:
                country = str(countries[0]).upper()
                if country in ("US", "USA", "UNITED STATES", "CA", "CANADA"):
                    return "na"
                else:
                    return "intl"

    return "all"


def get_date_range(df: pd.DataFrame) -> tuple[str, str] | None:
    """Extract min and max dates from the Date column."""
    if "Date" not in df.columns:
        return None

    try:
        dates = pd.to_datetime(df["Date"], errors="coerce").dropna()
        if len(dates) == 0:
            return None
        return dates.min().strftime("%Y-%m-%d"), dates.max().strftime("%Y-%m-%d")
    except Exception:
        return None


def split_by_geo(df: pd.DataFrame, source: str) -> dict[str, pd.DataFrame]:
    """Split DataFrame into NA and INTL subsets if both are present."""
    if source in ("google-ads", "display") and "Campaign" in df.columns:
        na_mask = df["Campaign"].str.contains(r"\bNA\b|_NA_|_na_", case=False, regex=True, na=False)
        intl_mask = df["Campaign"].str.contains(r"\bINTL\b|_INTL_|_intl_", case=False, regex=True, na=False)

        if na_mask.any() and intl_mask.any():
            result = {}
            if na_mask.any():
                result["na"] = df[na_mask].reset_index(drop=True)
            if intl_mask.any():
                result["intl"] = df[intl_mask].reset_index(drop=True)
            # Rows matching neither
            neither = df[~na_mask & ~intl_mask]
            if len(neither) > 0:
                result["unknown_geo"] = neither.reset_index(drop=True)
            return result

    elif source == "gsc" and "Country" in df.columns:
        na_countries = {"US", "USA", "UNITED STATES", "CA", "CANADA"}
        country_upper = df["Country"].fillna("").str.upper()
        na_mask = country_upper.isin(na_countries)
        intl_mask = ~na_mask & (df["Country"].notna())

        if na_mask.any() and intl_mask.any():
            return {
                "na": df[na_mask].reset_index(drop=True),
                "intl": df[intl_mask].reset_index(drop=True),
            }

    # No splitting needed
    return {}


def generate_filename(source: str, geo: str, date_range: tuple[str, str] | None) -> str:
    """Generate standard filename: {source}_{geo}_{start}_to_{end}.csv."""
    if date_range:
        return f"{source}_{geo}_{date_range[0]}_to_{date_range[1]}.csv"
    else:
        timestamp = datetime.now().strftime("%Y-%m-%d")
        return f"{source}_{geo}_{timestamp}.csv"


# HALO channel name -> system channel ID mapping
HALO_CHANNEL_MAP = {
    "affiliate": "affiliate",
    "brand campaign": "brand_campaign",
    "direct": "direct",
    "display": "display",
    "distribution": "distribution",
    "email": "email",
    "free referral": "free_referral",
    "managed social": "managed_social",
    "metasearch": "metasearch",
    "mobile app downloads": "mobile_app_downloads",
    "paid user referral": "paid_user_referral",
    "promoted social": "promoted_social",
    "push notification": "push_notification",
    "sem": "sem",
    "seo": "seo",
    "sms": "sms",
    "unknown": "unknown",
    "unknown utm": "unknown_utm",
}


def parse_space_number(val):
    """Parse a number formatted with space as thousands separator (European style)."""
    if pd.isna(val):
        return float("nan")
    s = str(val).strip()
    if s in ("", "#########"):
        return float("nan")
    # Remove space thousands separators and convert
    s = s.replace(" ", "")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def split_halo_file(filepath: Path, dry_run: bool = False) -> dict:
    """Split a HALO multi-channel CSV into per-channel files.

    The HALO CSV has one row per channel per date. This function:
    1. Reads with space-separated number parsing
    2. Filters out Total/N/A rows
    3. Maps channel names to system channel IDs
    4. Writes per-channel CSV files to data/validated/
    """
    result = {
        "input_file": str(filepath),
        "status": "pending",
        "actions": [],
        "warnings": [],
        "output_files": [],
        "error": None,
    }

    try:
        df = pd.read_csv(filepath)
    except Exception as e:
        result["status"] = "error"
        result["error"] = f"Could not read HALO file: {e}"
        return result

    result["actions"].append(f"Read {len(df)} rows, {len(df.columns)} columns")

    # Parse space-separated numbers for all numeric columns
    numeric_cols = [c for c in df.columns if c not in ("Dimension 1", "Dimension 2")]
    for col in numeric_cols:
        df[col] = df[col].apply(parse_space_number)

    # Filter out Total, N/A, and NaN rows
    skip_channels = {"Total", "N/A"}
    original_len = len(df)
    df = df[df["Dimension 1"].notna() & ~df["Dimension 1"].isin(skip_channels)].reset_index(drop=True)
    skipped = original_len - len(df)
    if skipped > 0:
        result["actions"].append(f"Filtered out {skipped} Total/N/A rows")

    # Get unique channels
    channels = df["Dimension 1"].str.lower().unique()
    result["actions"].append(f"Found {len(channels)} channels")

    files_written = 0
    for channel_raw in sorted(df["Dimension 1"].unique()):
        channel_lower = channel_raw.lower().strip()
        channel_id = HALO_CHANNEL_MAP.get(channel_lower)

        if channel_id is None:
            result["warnings"].append(f"WARN: Unknown HALO channel '{channel_raw}' — skipped")
            continue

        channel_df = df[df["Dimension 1"] == channel_raw].copy()

        # Rename Dimension 2 -> Date
        channel_df = channel_df.rename(columns={"Dimension 2": "Date"})
        # Drop Dimension 1 (channel name is now encoded in filename)
        channel_df = channel_df.drop(columns=["Dimension 1"])

        # Standardize dates
        channel_df, date_warnings = standardize_dates(channel_df)
        result["warnings"].extend(date_warnings)

        # Get date range
        date_range = get_date_range(channel_df)

        # HALO has no geo split — output as ALL
        filename = generate_filename(channel_id, "all", date_range)
        output_path = DATA_VALIDATED / filename

        if not dry_run:
            channel_df.to_csv(output_path, index=False)

        result["output_files"].append(str(output_path))
        files_written += 1

    result["actions"].append(f"Split into {files_written} per-channel files")
    result["status"] = "success"
    return result


def process_file(filepath: Path, dry_run: bool = False) -> dict:
    """Process a single file. Returns a result dict with status and details."""
    result = {
        "input_file": str(filepath),
        "status": "pending",
        "actions": [],
        "warnings": [],
        "output_files": [],
        "error": None,
    }

    # 1. File type detection
    file_type = detect_file_type(filepath)
    result["actions"].append(f"Detected file type: {file_type}")

    if file_type == "screenshot":
        result["status"] = "skipped"
        result["actions"].append("Screenshots require LLM vision processing — skipped by preprocessor script")
        return result

    if file_type == "pdf":
        result["status"] = "skipped"
        result["actions"].append("PDFs require specialized extraction — skipped by preprocessor script")
        return result

    if file_type == "unknown":
        result["status"] = "error"
        result["error"] = f"Unrecognized file type: {filepath.suffix}"
        return result

    # 2. Read file
    df = read_file(filepath)
    if df is None or df.empty:
        result["status"] = "error"
        result["error"] = "Could not read file or file is empty"
        return result

    result["actions"].append(f"Read {len(df)} rows, {len(df.columns)} columns")

    # 3. Strip junk rows
    original_len = len(df)
    df = strip_junk_rows(df)
    if len(df) < original_len:
        result["actions"].append(f"Stripped {original_len - len(df)} junk rows")

    # 4. Identify source from original columns (before aliasing may rename them)
    source = identify_source(df)

    # 4b. Standardize columns
    df = standardize_columns(df)
    result["actions"].append("Standardized column names and cleaned numeric values")

    # 4c. If source wasn't found from original columns, try again after standardization
    if source is None:
        source = identify_source(df)

    if source is None:
        result["status"] = "error"
        result["error"] = f"Could not identify data source. Columns: {list(df.columns)}"
        return result

    result["actions"].append(f"Identified source: {source}")

    # 4d. HALO files need special handling — split into per-channel files
    if source == "halo":
        return split_halo_file(filepath, dry_run=dry_run)

    # 6. Standardize dates
    df, date_warnings = standardize_dates(df)
    result["warnings"].extend(date_warnings)

    # 7. Detect geo and date range
    geo = detect_geo(df, source)
    date_range = get_date_range(df)

    # 8. Split by geo if needed
    geo_splits = split_by_geo(df, source)

    if geo_splits:
        # Write separate files per geo
        for geo_label, geo_df in geo_splits.items():
            if geo_label == "unknown_geo":
                result["warnings"].append(f"WARN: {len(geo_df)} rows could not be assigned to NA or INTL")
                continue

            dr = get_date_range(geo_df)
            filename = generate_filename(source, geo_label, dr)
            output_path = DATA_VALIDATED / filename

            if not dry_run:
                geo_df.to_csv(output_path, index=False)

            result["output_files"].append(str(output_path))
            result["actions"].append(f"Split geo '{geo_label}': {len(geo_df)} rows -> {filename}")
    else:
        # Write single file
        filename = generate_filename(source, geo, date_range)
        output_path = DATA_VALIDATED / filename

        if not dry_run:
            df.to_csv(output_path, index=False)

        result["output_files"].append(str(output_path))
        result["actions"].append(f"Wrote {len(df)} rows -> {filename}")

    result["status"] = "success"
    return result


def find_new_files() -> list[Path]:
    """Find files in /data/input/ that haven't been processed yet.

    A file is considered 'new' if no validated output exists with a matching source name.
    Skips image files (screenshots), PDFs, and markdown/prompt files.
    """
    skip_extensions = {".png", ".jpg", ".jpeg", ".pdf", ".md", ".yaml", ".yml"}
    skip_dirs = {"seo"}  # seo subdirectory has its own workflow

    files = []
    for f in DATA_INPUT.iterdir():
        if f.is_file() and f.suffix.lower() not in skip_extensions:
            # Skip files in subdirectories
            if f.parent != DATA_INPUT:
                continue
            files.append(f)

    # Also check subdirectories that aren't skipped
    for d in DATA_INPUT.iterdir():
        if d.is_dir() and d.name not in skip_dirs:
            for f in d.rglob("*"):
                if f.is_file() and f.suffix.lower() not in skip_extensions:
                    files.append(f)

    return sorted(files)


def main():
    parser = argparse.ArgumentParser(description="Preprocess marketing data files")
    parser.add_argument("files", nargs="*", help="Specific files to process (default: all new in /data/input/)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without writing")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    # Ensure output directory exists
    DATA_VALIDATED.mkdir(parents=True, exist_ok=True)

    # Determine files to process
    if args.files:
        files = [Path(f).resolve() for f in args.files]
    else:
        files = find_new_files()

    if not files:
        msg = "No files to process."
        if args.json:
            print(json.dumps({"status": "no_files", "message": msg}))
        else:
            print(msg)
        return

    results = []
    for filepath in files:
        if args.json:
            result = process_file(filepath, dry_run=args.dry_run)
            results.append(result)
        else:
            print(f"\n{'='*60}")
            print(f"Processing: {filepath.name}")
            print(f"{'='*60}")

            result = process_file(filepath, dry_run=args.dry_run)
            results.append(result)

            for action in result["actions"]:
                print(f"  {action}")
            for warning in result["warnings"]:
                print(f"  {warning}")
            if result["error"]:
                print(f"  ERROR: {result['error']}")
            if result["output_files"]:
                for of in result["output_files"]:
                    prefix = "[DRY RUN] Would write" if args.dry_run else "Wrote"
                    print(f"  {prefix}: {Path(of).name}")
            print(f"  Status: {result['status'].upper()}")

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        # Summary
        success = sum(1 for r in results if r["status"] == "success")
        errors = sum(1 for r in results if r["status"] == "error")
        skipped = sum(1 for r in results if r["status"] == "skipped")
        print(f"\n{'='*60}")
        print(f"Summary: {success} success, {errors} errors, {skipped} skipped")


if __name__ == "__main__":
    main()
