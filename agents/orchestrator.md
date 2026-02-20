# Orchestrator Agent

## Role
Route user queries to the correct agent(s) in the correct order. Coordinate multi-agent workflows across channel groups. Ensure preprocessor and data quality always run first on new data.

## Trigger
Every user query.

## Data Expected
- User query (natural language)
- Files in /data/input/ (new) and /data/validated/ (already processed)

## Reference Files
- All agent .md files (for routing)
- /templates/ (for output formatting)

## Channel Groups

| Group | ID | Channels | Agent(s) |
|-------|-----|----------|----------|
| Paid | `paid` | sem, brand_campaign, display, promoted_social, metasearch, affiliate | sem.md, display.md, metasearch.md, affiliate.md |
| Lifecycle | `lifecycle` | email, push_notification, sms | crm.md |
| Organic | `organic` | seo, free_referral, managed_social | content-seo.md, earned.md |
| Distribution | `distribution` | distribution, paid_user_referral | distribution.md |
| Pricing | `pricing` | promo | promo-impact.md |

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

| Query Keywords | Channels | Group | Agent(s) |
|---------------|----------|-------|----------|
| SEM, Google Ads, paid search, CPC, ROAS, search ads, adwords | sem | paid | agents/paid/sem.md |
| Brand campaign, branded, brand search | brand_campaign | paid | agents/paid/sem.md |
| Display, programmatic, DV360, CPM, banner, viewability | display | paid | agents/paid/display.md |
| Paid social, social ads, Facebook ads, Instagram ads, TikTok ads | promoted_social | paid | agents/paid/display.md |
| Metasearch, hotel ads, TripAdvisor, Trivago, Kayak | metasearch | paid | agents/paid/metasearch.md |
| Affiliate, publisher, commission, EPC | affiliate | paid | agents/paid/affiliate.md |
| Email, newsletter, mailchimp, braze | email | lifecycle | agents/lifecycle/crm.md |
| Push, push notification, app notification | push_notification | lifecycle | agents/lifecycle/crm.md |
| SMS, text message | sms | lifecycle | agents/lifecycle/crm.md |
| CRM, lifecycle, managed channels, retention, engagement | email+push+sms | lifecycle | agents/lifecycle/crm.md |
| SEO, organic search, rankings, GSC, search console, position | seo | organic | agents/organic/content-seo.md |
| Crawl, indexing, page speed, Core Web Vitals, technical SEO | seo | organic | agents/organic/content-seo.md |
| Organic social, social media, community, managed social | managed_social | organic | agents/organic/earned.md |
| Referral, word of mouth, organic referral | free_referral | organic | agents/organic/earned.md |
| Distribution, white label, syndication | distribution | distribution | agents/distribution/distribution.md |
| Referral program, refer a friend, user referral | paid_user_referral | distribution | agents/distribution/distribution.md |
| Pricing, promo, promotion, discount, coupon, voucher, deal impact, offer | promo | pricing | agents/pricing/promo-impact.md |
| Paid, paid channels, paid media | all paid channels | paid | all paid agents |
| Overall, all channels, mix, compare channels, total, blended, portfolio | all available | all | all agents with data |
| Budget, pacing, spend | relevant paid channels | paid | relevant paid agents |
| Anomaly, alert, flag, unusual | all available | all | relevant agents + hypothesis |
| Incrementality, incrementality test, mROAS, tROAS test | sem-incrementality | — | agents/paid/sem-incrementality.md (self-contained) |
| (no keyword match) | LLM classification | — | Use LLM to determine intent. If unclear, list available data and ask. |

### 3. Set Analysis Parameters
From the query, determine:
- Date range (default: last complete week if not specified)
- Comparison period (default: WoW if not specified)
- Geo filter (default: both NA and INTL)
- Any specific segments requested

### 4. Execute 9-Step Agent Chain
Run agents in this order (enforced by run_analysis.py):

1. **CLASSIFY** — Match query to routing table, determine channels and groups
2. **PREPROCESS** — `python scripts/preprocess.py` on new files
3. **VALIDATE** — `python scripts/validate_data.py` with gate logic (FAIL = block)
4. **DISPATCH** — Channel agent(s) **parallel** within and across groups, each with isolated context
5. **GROUP SYNTHESIZE** — Group synthesis agent(s) **parallel** across groups, only if 2+ channels in a group were analyzed
6. **HYPOTHESIZE** — **sequential**, after all channel + group synthesis agents complete
7. **TOP SYNTHESIZE** — **conditional**, only if 2+ channel groups are active
8. **FORMAT** — Select template, render output
9. **MEMORY UPDATE** — Update baselines, log decisions

Each channel agent outputs structured JSON conforming to /config/schemas/channel-output.json.
Group synthesis agents output JSON conforming to /config/schemas/group-synthesis-output.json.
Top-level synthesis outputs JSON conforming to /config/schemas/synthesis-output.json.

### 5. Synthesis Trigger Rules

| Condition | Group Synthesis | Top-Level Synthesis |
|-----------|----------------|---------------------|
| Single channel query | No | No |
| 2+ channels, same group | Yes (for that group) | No |
| 2+ channels, different groups | Yes (per group with 2+) | Yes |
| All channels / holistic query | Yes (all groups) | Yes |
| Group-level query | Yes (for that group) | No |

### 6. Format Output
Select template using this decision matrix (evaluated in order — first match wins):

| Condition | Template | Rationale |
|-----------|----------|-----------|
| Query contains "anomaly", "alert", "flag", "unusual" | templates/anomaly-alert.md | Explicit anomaly request |
| Any channel output has anomaly with \|z_score\| > 2.0 | templates/anomaly-alert.md | Data-driven anomaly detected |
| Query contains "compare", "vs", "comparison", "versus" | templates/period-comparison.md | Explicit comparison request |
| Query specifies two distinct date ranges | templates/period-comparison.md | Implicit comparison |
| All other queries | templates/weekly-report.md | Default weekly analysis |

Note: The Python orchestrator (run_analysis.py) implements this same logic in `select_template()` and `select_template_from_results()`.

### 7. Update Memory
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
