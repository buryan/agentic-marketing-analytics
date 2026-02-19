# Marketing Analytics Agent System

## Purpose
Agentic system for automated marketing analytics across Paid (SEM, Display, Affiliate) and SEO channels for an ecommerce marketplace. All analysis runs on imported data only (CSV, screenshots, exports). No API connections. All agents are .md prompt files. Claude reasons directly over data.

## Architecture
Multi-agent hierarchy. Each agent is a .md file with a defined role, expected inputs, reference files, and output format.

## Processing Chain (mandatory order)
Every analysis request follows this exact sequence. Never skip steps.

1. PREPROCESSOR (agents/preprocessor.md) - standardize file names, columns, dates, split combined files
2. DATA QUALITY (agents/data-quality.md) - validate schema, completeness, sanity, cross-source consistency
3. ORCHESTRATOR (agents/orchestrator.md) - classify query, select agent(s), set date range
4. CHANNEL AGENT(S) - analyze validated data with baselines and benchmarks
5. HYPOTHESIS AGENT (agents/hypothesis.md) - explain WHY metrics moved, assign confidence
6. SYNTHESIS AGENT (agents/cross-channel/synthesis.md) - only if multi-channel, cross-channel view + contradictions + ICE-scored actions
7. MEMORY UPDATE - append new baselines, log decisions, update known issues

## Data Rules
- All inputs go to /data/input/
- Only validated data (QC passed) is used for analysis
- All monetary values in USD
- Dates: YYYY-MM-DD internally, DD-MM-YYYY in user-facing output
- NA (North America, ~80% of business) and INTL (~20%) always reported separately, then blended
- Screenshots: extracted values tagged with [FROM SCREENSHOT]
- Every numeric claim must trace to a source file. No hallucinated numbers.

## Agent Invocation Rules
- When new files appear in /data/input/, ALWAYS run preprocessor then data-quality first
- Orchestrator determines which channel agent(s) to invoke based on query keywords
- Hypothesis agent runs after every channel agent
- Synthesis agent runs only when 2+ channel agents are invoked
- After every analysis run, update relevant memory files

## Output Standards
- Tables preferred over paragraphs
- Every table includes: metric | current period | prior period | delta % | delta $
- Traffic light system: GREEN (on/above plan), YELLOW (within 5%), RED (>5% below)
- Every insight must cite the source file and relevant data point
- Assumptions labeled explicitly
- Conflicting data sources flagged, never silently resolved

## Extension Protocol
To add a new channel or data source:
1. Create /data/schemas/{source}.yaml
2. Add validation rules to /config/data-quality-rules.yaml
3. Add metric definitions to /config/metrics.yaml if new metrics needed
4. Add benchmarks to /config/benchmarks.yaml if available
5. Create /agents/{category}/{agent}.md
6. Update /agents/orchestrator.md routing table
7. Create /memory/baselines/{channel}.md
8. Test with real data end-to-end
9. Log change in /prompts/changelog.md

## Memory Update Protocol
After each analysis run:
- Update /memory/baselines/{channel}-weekly-baselines.md with new rolling averages
- If actions were recommended and user confirms, log to /memory/decisions-log.md
- If external factors discovered (storms, outages, algo updates), add to /memory/known-issues.md
- If budget or promo calendar changes noted, update /memory/context.md
