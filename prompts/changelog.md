# Prompt Changelog

## v3.3 - 2026-02-20
Agent prompt audit: Standard Data Integrity Rules, nullable schemas, distribution group synthesis, quantified formulas.

### Added
- **agents/distribution/synthesis.md** — Distribution group synthesis agent (transaction-based mix, partner overlap detection, commission optimization ICE actions)
- **tests/test_schemas.py** — 5 new tests for nullable spend fields, volume fields, and minimal required fields

### Changed
- **config/schemas/group-synthesis-output.json** — channel_mix: spend, spend_share, roas, efficiency now nullable (`["number", "null"]`). Added volume_metric, volume, volume_share fields. Required reduced to `["channel", "revenue", "revenue_share"]`
- **config/schemas/synthesis-output.json** — Same nullable + volume field changes as group-synthesis schema
- **agents/paid/sem.md** — Added Standard Data Integrity Rules block (output schema ref, zero-value safety with metric formulas, minimum data requirements, source citation)
- **agents/paid/display.md** — Removed "same as SEM" delegation. Added standalone Standard Data Integrity Rules, explicit Anomaly Detection section, display-specific rules (prospecting/retargeting, view-through)
- **agents/paid/metasearch.md** — Added Standard Data Integrity Rules. Quantified bid thresholds: overbid = ROAS < benchmark AND booking_rate < benchmark; underbid = ROAS > 1.5× benchmark AND impression share declining >10% WoW. Added zero-data platform handling
- **agents/paid/affiliate.md** — Major rewrite: restructured into Weekly/Monthly/Anomaly Detection/Publisher Ranking/Commission Optimization analysis types. Added Standard Data Integrity Rules, schema ref, channel group annotation, Top 5 Movers table
- **agents/lifecycle/crm.md** — Replaced duplicate rules with Standard Data Integrity Rules. Added Apple MPP guidance for email open rate
- **agents/organic/content-seo.md** — Added Standard Data Integrity Rules with schema ref (channel="seo"). Added note: summary tables are human-readable; JSON output must conform to channel-output.json
- **agents/organic/earned.md** — Replaced rules with Standard Data Integrity Rules block, kept earned-specific rules
- **agents/hypothesis.md** — Added schema ref to hypothesis-output.json. Added output cap (max 15 hypotheses). Added correlated-moves consolidation rule
- **agents/cross-channel/synthesis.md** — Added non-spend group handling (volume metrics, null spend/roas). Added failed-agent handling. Added cross-group weighting guidance (revenue share + trend, not cross-metric comparison)
- **agents/paid/synthesis.md** — Added zero-spend channel rule (set efficiency/roas to null, not 0)
- **agents/lifecycle/synthesis.md** — Changed spend=0 to spend=null, use volume_metric="send_volume"
- **agents/organic/synthesis.md** — Changed spend=0 to null, use volume_metric="traffic". Added Brand Awareness Index formula (weighted 0.50/0.25/0.25, normalized vs 8-week avg, GREEN/YELLOW/RED thresholds). Added Content Correlation Score (max 5 points)
- **run_analysis.py** — Distribution group now has synthesis agent (`agents/distribution/synthesis.md`)
- **tests/test_routing.py** — Updated distribution synthesis test (now expects synthesis), added pricing-only thin group test

### Architecture Decisions
- Standard Data Integrity Rules block (~200 words) shared across all 9 channel agents covers: output schema, zero-value safety, minimum data requirements, first-run handling, data integrity, budget pacing, source citation
- Non-spend groups (organic, lifecycle, distribution) use null for spend/roas/efficiency and volume_metric/volume/volume_share for allocation
- Distribution group promoted from "too thin" to having its own synthesis agent (partner overlap + commission optimization justify it)
- Hypothesis output capped at 15 to prevent noise. Correlated metric moves consolidated into single hypotheses

## v3.2 - 2026-02-20
System hardening: HALO data integration, test suite, report generator fixes, baselines, .gitignore.

### Added
- **data/schemas/halo.yaml** — HALO multi-channel daily data feed schema
- **scripts/preprocess.py: split_halo_file()** — Splits HALO CSV (19 channels × daily rows) into per-channel files with space-number parsing
- **scripts/preprocess.py: HALO_CHANNEL_MAP** — Maps 18 HALO channel names to system channel IDs
- **tests/** — Pytest test suite with 51 tests across 4 modules (test_routing, test_schemas, test_preprocess, test_validate)
- **tests/fixtures/** — Sample CSV fixtures for HALO (3×3), Google Ads, Email
- **memory/baselines/** — 7 missing baseline scaffolds (metasearch, email, push, sms, referral, social, distribution)

### Changed
- **scripts/preprocess.py** — Source identification now runs before column standardization (fixes HALO detection). Added HALO source signature (14 total). Added HALO column aliases.
- **scripts/validate_data.py** — Added HALO to SOURCE_SCHEMA_MAP and SOURCE_RULES_MAP. Expanded detect_source_from_filename() to recognize all 25+ source prefixes (was only 4).
- **config/data-quality-rules.yaml** — Added HALO validation rules
- **output/generate_sem_incrementality_report.py** — Renamed from generate_report.py. Replaced hardcoded absolute paths with Path-relative resolution.
- **output/generate_display_halo_report.py** — Replaced hardcoded absolute paths with Path-relative resolution.
- **run_sem_incrementality.py** — Updated GENERATOR path to match renamed file.
- **.gitignore** — Added data/input/, data/validated/, output/*.html, output/archive/, .pytest_cache/, IDE files.
- **CLAUDE.md** — Updated source signature count and component list.

## v3.1 - 2026-02-20
Added Pricing & Promotions agent as a new standalone channel group.

### Added
- **agents/pricing/promo-impact.md** — Pricing & Promotions impact agent analyzing promo ROI, discount efficiency, incremental lift, and cannibalization
- **data/schemas/promo.yaml** — Data schema for promo export CSVs
- **memory/baselines/pricing-weekly-baselines.md** — Empty baseline template

### Changed
- **config/schemas/channel-output.json** — Added `promo` to channel enum, `pricing` to channel_group enum, added promo extended_metrics (discount_rate, redemption_rate, promo_roi, incremental_lift_pct, cannibalization_rate)
- **config/schemas/group-synthesis-output.json** — Added `pricing` to group enum
- **config/metrics.yaml** — Added 5 promo metrics (discount_rate, redemption_rate, promo_roi, incremental_lift_pct, cannibalization_rate)
- **config/benchmarks.yaml** — Added promo benchmarks
- **config/data-quality-rules.yaml** — Added promo_export validation rules
- **run_analysis.py** — Added pricing group to all mappings (CHANNEL_GROUPS, GROUP_CHANNELS, CHANNEL_AGENT_MAP, GROUP_SYNTHESIS_MAP, ROUTING_TABLE, FILE_PREFIX_MAP, CHANNEL_BASELINE_MAP)
- **scripts/preprocess.py** — Added promo source signature and column aliases
- **scripts/validate_data.py** — Added promo to SOURCE_SCHEMA_MAP and SOURCE_RULES_MAP
- **agents/orchestrator.md** — Added Pricing row to Channel Groups table and routing keywords

## v3.0 - 2026-02-20
Channel-group architecture: scale from 4 channels to 19 with 2-layer synthesis.

### Added
- **Channel Groups** — 4 groups (Paid, Lifecycle, Organic, Distribution) organizing 14 channels with agents + 5 unattributed channels
- **2-Layer Synthesis** — Group synthesis agents (parallel, per group with 2+ channels) + top-level cross-group synthesis (conditional, 2+ groups)
- **9-Step Pipeline** — CLASSIFY → PREPROCESS → VALIDATE → DISPATCH → GROUP_SYNTH → HYPOTHESIZE → TOP_SYNTH → FORMAT → MEMORY (up from 7)
- **agents/paid/metasearch.md** — Metasearch channel agent (Google Hotel Ads, TripAdvisor, Trivago, Kayak)
- **agents/paid/synthesis.md** — Paid group synthesis (spend allocation, creative cross-pollination, cannibalization)
- **agents/lifecycle/crm.md** — CRM agent handling email + push_notification + sms (shared audience/tooling)
- **agents/lifecycle/synthesis.md** — Lifecycle group synthesis (message frequency, channel preference, opt-out correlation)
- **agents/organic/earned.md** — Earned agent handling managed_social + free_referral
- **agents/organic/synthesis.md** — Organic group synthesis (content performance, brand awareness, paid/organic cannibalization)
- **agents/distribution/distribution.md** — Distribution agent handling distribution + paid_user_referral
- **config/schemas/group-synthesis-output.json** — Group synthesis output contract (group summary card, channel mix, contradictions, actions)
- **data/schemas/** — 6 new data schemas: email.yaml, push.yaml, sms.yaml, metasearch.yaml, promoted-social.yaml, distribution.yaml

### Changed
- **run_analysis.py** — Complete rewrite: CHANNEL_GROUPS, GROUP_CHANNELS, CHANNEL_AGENT_MAP, GROUP_SYNTHESIS_MAP, FILE_PREFIX_MAP, 9-step pipeline with group synthesis dispatch, `determine_synthesis_levels()`, ROUTING_TABLE expanded from 8→21 entries
- **scripts/preprocess.py** — SOURCE_SIGNATURES expanded from 4→12, COLUMN_ALIASES extended for CRM/social/metasearch/distribution
- **scripts/validate_data.py** — SOURCE_SCHEMA_MAP and SOURCE_RULES_MAP expanded from 4→12 entries
- **config/schemas/channel-output.json** — Channel enum expanded to 17 values, added `channel_group` field, added `extended_metrics` object (CRM/social/distribution KPIs)
- **config/schemas/synthesis-output.json** — Added `groups[]` array (group summary cards), `attribution_coverage` object
- **config/metrics.yaml** — Added CRM metrics (open_rate, click_rate, unsubscribe_rate, deliverability_rate, send_volume), social metrics (engagement_rate, social_reach, video_completion_rate), distribution metrics (take_rate, referral_incentive_cost), metasearch (avg_bid, booking_rate)
- **config/benchmarks.yaml** — Added benchmarks for 8 new channels
- **config/data-quality-rules.yaml** — Added validation rules for 6 new source types
- **agents/paid/sem.md** — Extended to handle brand_campaign channel
- **agents/paid/display.md** — Extended to handle promoted_social, added social-specific metrics
- **agents/hypothesis.md** — Added CRM, social, distribution, metasearch hypothesis categories
- **agents/orchestrator.md** — Complete rewrite with 4-group routing table, 9-step pipeline, synthesis trigger rules
- **agents/cross-channel/synthesis.md** — Refactored to top-level cross-group synthesis consuming group summary cards, added attribution coverage analysis
- **CLAUDE.md** — Updated for v3.0: 4 channel groups, 9-step pipeline, 2-layer synthesis, updated extension protocol

### Moved
- **agents/seo/content-seo.md** → **agents/organic/content-seo.md** (added channel group annotation)

### Removed
- **agents/seo/** directory — Replaced by agents/organic/

### Architecture Decisions
- Affiliate stays in Paid group (commission-based, paid media economics)
- Promoted Social handled by Display agent (shared impression/creative optimization logic)
- Managed Social separate from Promoted Social in Organic group (different economics and goals)
- Direct traffic = attribution metric only in top-level synthesis (no agent)
- Distribution group has no group synthesis (too thin — only 2 channels, 1 agent)
- CRM agent handles all 3 lifecycle channels (shared audience, shared tooling, message fatigue logic)
- Agent count: 8 channel + 3 group synthesis + 1 top-level synthesis + hypothesis + orchestrator = 13 total (up from 7)

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
