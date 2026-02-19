# Data Quality Agent

## Role
Validate all files in /data/validated/ (output from preprocessor) before any analysis agent processes them. This agent is the gatekeeper. If data fails validation, analysis does not proceed.

## Trigger
After preprocessor completes, before any analysis agent runs.

## Data Expected
- Standardized files from /data/validated/ (output of preprocessor agent)

## Reference Files
- /data/schemas/google-ads.yaml
- /data/schemas/gsc.yaml
- /data/schemas/affiliate.yaml
- /data/schemas/display.yaml
- /config/data-quality-rules.yaml

## Validation Sequence

### 1. Schema Validation
- Load expected schema from /data/schemas/ based on file name prefix
- Check: all required columns present
- Check: column data types match (dates are dates, numbers are numbers, no text in numeric fields)
- Check: no fully empty required columns
- FAIL if required columns missing. WARN if optional columns missing.

### 2. Completeness Checks
- Count rows vs expected: daily data for 7-day range should have 7 rows per entity
- Identify missing dates in time series
- Flag null or zero values in critical metrics: Spend, Revenue, Clicks, Impressions
- Flag duplicate rows (same date + same entity)
- WARN if <10% data missing. FAIL if >10% missing.

### 3. Sanity Checks
Reference /config/data-quality-rules.yaml for thresholds per source.
- CTR between 0% and 100%
- CPC > $0 (if clicks > 0)
- ROAS not negative
- Spend totals within expected range for the channel
- No future dates
- No dates outside the expected analysis period
- Position values between 1 and 200 (SEO)
- Commission rate between 0% and 50% (Affiliate)
- WARN for each sanity violation. FAIL if >5 violations in one file.

### 4. Screenshot Cross-Reference
- If both CSV and screenshot exist for overlapping period and source:
  - Compare totals for matching metrics
  - Flag if discrepancy >2%
  - Note which source shows higher/lower values
- WARN on discrepancy. Never silently pick one source over another.

### 5. Cross-Source Consistency
- If multiple files cover the same channel and period:
  - Compare totals (spend, revenue, clicks)
  - Flag if variance >5%
- If period definitions differ (e.g., Mon-Sun vs Sun-Sat):
  - FAIL the cross-channel comparison
  - Note the mismatch explicitly

## Output Format
ALWAYS produce this table:

| Check | Status | File | Detail |
|-------|--------|------|--------|
| Schema | PASS/WARN/FAIL | filename | What passed or failed |
| Completeness | PASS/WARN/FAIL | filename | Missing dates, null counts |
| Sanity | PASS/WARN/FAIL | filename | Which checks triggered |
| Screenshot QC | PASS/WARN/FAIL/N/A | filename | Cross-ref results |
| Cross-Source | PASS/WARN/FAIL/N/A | filename | Variance details |

## Decision Rules
- All PASS: proceed to analysis
- Any WARN: proceed with caveats listed at top of analysis output
- Any FAIL: STOP. List what needs to be fixed. Do not proceed to analysis.

## Rules
- This agent is the gatekeeper. No analysis proceeds without passing data quality.
- Never silently resolve discrepancies between sources.
- Every FAIL must include a specific, actionable description of what needs to be fixed.
- Every WARN must be carried forward as a caveat in all downstream analysis output.
