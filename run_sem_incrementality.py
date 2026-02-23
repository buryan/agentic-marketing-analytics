#!/usr/bin/env python3
"""SEM Incrementality Test — Runner Script

One-command execution: validate inputs, archive old report, generate new report, verify output.
"""

import os
import sys
import shutil
import subprocess
from datetime import datetime

# ── Paths ──────────────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(ROOT, "data", "input")
OUTPUT_DIR = os.path.join(ROOT, "output")
ARCHIVE_DIR = os.path.join(OUTPUT_DIR, "archive")
GENERATOR = os.path.join(OUTPUT_DIR, "generate_sem_incrementality_report.py")
REPORT = os.path.join(OUTPUT_DIR, "sem-incrementality-report.html")
PERF_FILE = os.path.join(INPUT_DIR, "sem_incrementality_data.xlsx")
CE_FILE = os.path.join(INPUT_DIR, "sem_incrementality_google_ads_changes.xlsx")

MIN_REPORT_KB = 10  # minimum expected report size


def validate():
    """Check that all required inputs exist."""
    print("=" * 60)
    print("STEP 1: Validate inputs")
    print("=" * 60)
    errors = []
    for label, path in [
        ("Performance data", PERF_FILE),
        ("Change events data", CE_FILE),
        ("Report generator", GENERATOR),
    ]:
        if os.path.isfile(path):
            size_kb = os.path.getsize(path) / 1024
            print(f"  OK  {label}: {os.path.basename(path)} ({size_kb:.0f} KB)")
        else:
            print(f"  FAIL  {label}: NOT FOUND at {path}")
            errors.append(path)
    if errors:
        print(f"\nAborted — {len(errors)} missing file(s).")
        sys.exit(1)
    print()


def archive():
    """Move existing report to archive/ with timestamp."""
    print("=" * 60)
    print("STEP 2: Archive previous report")
    print("=" * 60)
    if not os.path.isfile(REPORT):
        print("  No existing report to archive.\n")
        return
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    dest = os.path.join(ARCHIVE_DIR, f"sem-incrementality-report_{ts}.html")
    shutil.copy2(REPORT, dest)
    size_kb = os.path.getsize(dest) / 1024
    print(f"  Archived: {os.path.basename(dest)} ({size_kb:.0f} KB)\n")


def generate():
    """Run generate_report.py via subprocess."""
    print("=" * 60)
    print("STEP 3: Generate new report")
    print("=" * 60)
    result = subprocess.run(
        [sys.executable, GENERATOR],
        capture_output=True,
        text=True,
    )
    if result.stdout:
        for line in result.stdout.strip().split("\n"):
            print(f"  {line}")
    if result.returncode != 0:
        print(f"\n  ERROR: Generator exited with code {result.returncode}")
        if result.stderr:
            for line in result.stderr.strip().split("\n"):
                print(f"  {line}")
        sys.exit(1)
    print()


def verify():
    """Confirm the report was created and meets minimum size."""
    print("=" * 60)
    print("STEP 4: Verify output")
    print("=" * 60)
    if not os.path.isfile(REPORT):
        print(f"  FAIL: Report not found at {REPORT}")
        sys.exit(1)
    size_kb = os.path.getsize(REPORT) / 1024
    if size_kb < MIN_REPORT_KB:
        print(f"  FAIL: Report too small ({size_kb:.0f} KB < {MIN_REPORT_KB} KB minimum)")
        sys.exit(1)
    print(f"  OK  Report: {REPORT}")
    print(f"  OK  Size: {size_kb:.0f} KB")

    # Count archive files
    archive_count = 0
    if os.path.isdir(ARCHIVE_DIR):
        archive_count = len([f for f in os.listdir(ARCHIVE_DIR) if f.endswith(".html")])
    print(f"  Archive: {archive_count} previous report(s) in archive/\n")


def summary():
    """Print final summary."""
    print("=" * 60)
    print("DONE")
    print("=" * 60)
    print(f"  Report: {REPORT}")
    print(f"  Open in browser to verify all 8 tabs render correctly.")


if __name__ == "__main__":
    validate()
    archive()
    generate()
    verify()
    summary()
