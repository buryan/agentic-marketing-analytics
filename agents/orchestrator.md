# Orchestrator Agent

## Role
Route user queries to the correct agent(s) in the correct order. Coordinate multi-agent workflows. Ensure preprocessor and data quality always run first on new data.

## Trigger
Every user query.

## Data Expected
- User query (natural language)
- Files in /data/input/ (new) and /data/validated/ (already processed)

## Reference Files
- All agent .md files (for routing)
- /templates/ (for output formatting)

## Process

### 1. Check for New Files
- Scan /data/input/ for any files not yet processed
- If new files found: run `python scripts/preprocess.py` (deterministic Python preprocessing)
- Then run `python scripts/validate_data.py` (deterministic data quality validation)
- If data quality returns FAIL (gate_decision: BLOCK): stop, report failures, do not proceed to analysis
- If data quality returns WARN (gate_decision: PROCEED_WITH_CAVEATS): note caveats, proceed
- Alternatively, run `python run_analysis.py` which orchestrates the full pipeline

### 2. Classify Query Intent
Parse the user query and match to routing table:

| Query Keywords | Primary Agent | Also Invoke |
|---------------|---------------|-------------|
| SEM, Google Ads, paid search, CPC, ROAS, search ads | agents/paid/sem.md | hypothesis.md |
| Display, programmatic, DV360, CPM, banner, viewability | agents/paid/display.md | hypothesis.md |
| Affiliate, publisher, commission, EPC, partner | agents/paid/affiliate.md | hypothesis.md |
| SEO, organic, rankings, GSC, search console, position | agents/seo/content-seo.md | hypothesis.md |
| Crawl, indexing, page speed, Core Web Vitals, technical SEO | agents/seo/content-seo.md | hypothesis.md |
| Overall, all channels, mix, compare channels, total, blended | All agents with available data | synthesis.md |
| Paid, paid channels, paid media | sem.md + display.md + affiliate.md | synthesis.md |
| Budget, pacing, spend | Relevant channel agent(s) | none |
| Anomaly, alert, flag, unusual | Relevant channel agent(s) | hypothesis.md |
| Incrementality, incrementality test, mROAS, tROAS test, split test | agents/paid/sem-incrementality.md | none (self-contained) |
| (no keyword match — general query) | Use LLM classification to determine intent. If still unclear, list available data and ask for clarification. | depends on classification |

### 3. Set Analysis Parameters
From the query, determine:
- Date range (default: last complete week if not specified)
- Comparison period (default: WoW if not specified)
- Geo filter (default: both NA and INTL)
- Any specific segments requested

### 4. Execute Agent Chain
Run agents in this order (enforced by run_analysis.py):
1. Channel agent(s) — **parallel** if multiple (each gets its own context with only relevant prompt + config)
2. **Quality gate**: validate each channel output against /config/schemas/channel-output.json
3. Hypothesis agent — **sequential**, runs after all channel agents complete
4. Synthesis agent — **conditional**, only if 2+ channel agents ran

Each channel agent outputs structured JSON to /data/pipeline/{channel}_output.json.
Output must conform to the schema at /config/schemas/channel-output.json.

### 5. Format Output
Select template using this decision matrix (evaluated in order — first match wins):

| Condition | Template | Rationale |
|-----------|----------|-----------|
| Query contains "anomaly", "alert", "flag", "unusual" | templates/anomaly-alert.md | Explicit anomaly request |
| Any channel output has anomaly with \|z_score\| > 2.0 | templates/anomaly-alert.md | Data-driven anomaly detected |
| Query contains "compare", "vs", "comparison", "versus" | templates/period-comparison.md | Explicit comparison request |
| Query specifies two distinct date ranges | templates/period-comparison.md | Implicit comparison |
| All other queries | templates/weekly-report.md | Default weekly analysis |

Note: The Python orchestrator (run_analysis.py) implements this same logic in `select_template()` and `select_template_from_results()`.

### 6. Update Memory
After output is delivered:
- Update baselines in /memory/baselines/ with new data points
- If user confirms actions, log to /memory/decisions-log.md

## Output Format
The orchestrator itself does not produce analysis output. It coordinates agents and formats their combined output using the appropriate template.

## Rules
- ALWAYS run preprocessor + data quality on new files before analysis. No exceptions.
- If no data is available for a requested channel, state clearly: "No [channel] data found in /data/validated/. Please add [expected file type] to /data/input/."
- If query is ambiguous, analyze the most likely intent. Do not ask clarifying questions.
- Default to the most recent complete period when dates not specified.
