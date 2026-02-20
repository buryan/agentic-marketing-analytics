# Prompt Changelog

## v2.0 - 2026-02-20
Architecture overhaul based on AI architecture review. Addresses the 10 critical findings.

### Added
- **run_analysis.py** — Python orchestrator enforcing the 7-step chain (P0). Replaces implicit prompt-based orchestration with code-enforced pipeline. Enables parallel channel agent execution.
- **scripts/preprocess.py** — Deterministic Python preprocessor (P1). Replaces LLM-based preprocessor.md. Handles file type detection, source identification, column standardization, date parsing, geo splitting, and standard naming. ~1s vs ~30s for LLM.
- **scripts/validate_data.py** — Deterministic Python data quality validator (P1). Replaces LLM-based data-quality.md. Implements 5-step validation: schema, completeness, sanity checks, cross-source consistency. Gate logic: FAIL=block, WARN=proceed. ~1s vs ~20s for LLM.
- **config/schemas/channel-output.json** — JSON Schema for channel agent output contracts (P0). All channel agents must produce structured JSON conforming to this schema.
- **config/schemas/hypothesis-output.json** — JSON Schema for hypothesis agent output contract.
- **config/schemas/synthesis-output.json** — JSON Schema for synthesis agent output contract.
- **data/pipeline/** — Inter-agent communication directory. Channel agents write JSON outputs here; orchestrator reads and routes.

### Changed
- **agents/orchestrator.md** — Added template selection decision matrix (P1), LLM fallback for unmatched queries (P1), updated to reference Python scripts and output contracts.
- **agents/seo/content-seo.md** — Absorbed technical-seo.md as conditional "Technical Health" subsection (P1). Activates when CWV/crawl data is present.
- **memory/decisions-log.md** — Redesigned with auto-population support from run_analysis.py (P2). Added status workflow (Open → Confirmed/Partial/Missed/Reversed/Declined).
- **memory/context.md** — Replaced empty placeholder fields with documentation on expected format.
- **CLAUDE.md** — Updated to reflect hybrid Python + LLM architecture, new extension protocol, context isolation, parallel execution.

### Removed
- **agents/seo/technical-seo.md** — Merged into content-seo.md. No crawl/CWV data existed; agent was never triggered. Reduces prompt payload by ~1.7 KB.

### Architecture Decisions
- Preprocessing and data validation are deterministic tasks — Python scripts eliminate LLM latency and non-determinism.
- Channel agents run in parallel as isolated sub-agents, each receiving only their own prompt (~8KB) instead of the full ~36KB payload.
- Structured JSON output contracts between agents enable automated quality validation.
- Template selection rules are explicit (decision matrix) rather than implicit ("select appropriate template").
- The decisions-log now supports auto-population from ICE-scored actions, creating a feedback loop for the hypothesis agent.

## v1.0 - 2026-02-19
- Initial build: full agent system
- Agents: orchestrator, preprocessor, data-quality, hypothesis, synthesis
- Channel agents: SEM, Display, Affiliate, Content SEO, Technical SEO
- Config: metrics, thresholds, benchmarks, data-quality-rules
- Schemas: Google Ads, GSC, Affiliate, Display
- Memory: baselines, decisions-log, known-issues, context
- Templates: weekly-report, anomaly-alert, period-comparison

## v1.1 - 2026-02-19
- Added: agents/paid/sem-incrementality.md — SEM incrementality test analysis agent
- Added: data/schemas/sem-incrementality.yaml — schema for incrementality test data
- Updated: orchestrator routing table with incrementality keywords
- Updated: CLAUDE.md with workflow orchestration, task management, core principles

## v1.2 - 2026-02-19
- First SEO organic performance analysis using agent system
- Generated: output/seo-content-report.html — 8-tab dashboard (Exec Summary, Daily Trends, Page Types, Top Pages, Queries, Deal Deep Dive, AI Commentary, Data Quality)
- Data: 7 CSVs covering daily overview (699 days), category performance, pages (1,291), queries (1,553), deal WoW (333), impression deltas (162)
- Updated: memory/baselines/seo-weekly-baselines.md with latest metrics
- Updated: memory/known-issues.md with Google AI Overview impact and SEO-specific issues
- Key finding: Position paradox — rankings improved 16→9 but clicks down 53%, likely due to Google AI Overviews
