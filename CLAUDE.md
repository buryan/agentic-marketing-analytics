# Marketing Analytics Agent System

## Purpose
Agentic system for automated marketing analytics across 5 channel groups (Paid, Lifecycle, Organic, Distribution, Pricing) covering 19 marketing channels for an ecommerce marketplace. All analysis runs on imported data only (CSV, screenshots, exports). No API connections. All agents are .md prompt files. Claude reasons directly over data.

## Architecture
Hybrid Python + LLM agent system. The Python orchestrator (`run_analysis.py`) enforces the processing chain, manages context isolation, and enables parallel execution. LLM agents handle reasoning-heavy tasks (analysis, hypothesis, synthesis). Deterministic Python scripts handle mechanical tasks (preprocessing, data quality validation).

### Key Components
- **run_analysis.py** — Master orchestrator enforcing the 9-step chain with 2-layer synthesis
- **scripts/preprocess.py** — Deterministic file standardization (12 source signatures)
- **scripts/validate_data.py** — Deterministic data quality validation with gate logic
- **agents/{group}/*.md** — LLM agent prompts organized by channel group (paid/, lifecycle/, organic/, distribution/)
- **config/schemas/*.json** — Structured output contracts (channel-output, group-synthesis-output, hypothesis-output, synthesis-output)
- **data/pipeline/** — Inter-agent communication via JSON files

### Channel Groups (5 groups, 15 channels with agents)
| Group | Channels | Agent(s) |
|-------|----------|----------|
| **Paid** | sem, brand_campaign, display, promoted_social, metasearch, affiliate | sem.md, display.md, metasearch.md, affiliate.md |
| **Lifecycle** | email, push_notification, sms | crm.md |
| **Organic** | seo, free_referral, managed_social | content-seo.md, earned.md |
| **Distribution** | distribution, paid_user_referral | distribution.md |
| **Pricing** | promo | promo-impact.md |

Unattributed channels (direct, unknown, unknown_utm) have no agents — surfaced as attribution coverage % in top-level synthesis.

### Standalone Pipelines (independent of agent chain)
- **run_display_halo.py** → Display Halo Effect analysis (Python + HTML)
- **run_sem_incrementality.py** → SEM Incrementality test analysis (Python + HTML)

## Processing Chain (mandatory order)
Every analysis request follows this exact 9-step sequence. Enforced by `run_analysis.py`. Never skip steps.

1. **CLASSIFY** — Match query to routing table, determine channels and groups
2. **PREPROCESS** (`scripts/preprocess.py`) — deterministic: standardize file names, columns, dates, split combined files
3. **VALIDATE** (`scripts/validate_data.py`) — deterministic: validate schema, completeness, sanity. Gate: FAIL = block, WARN = proceed with caveats
4. **DISPATCH** — Channel agent(s) **parallel** within and across groups, each with isolated context. Output: structured JSON per /config/schemas/channel-output.json
5. **GROUP SYNTHESIZE** — Group synthesis agent(s) **parallel** across groups, only if 2+ channels in a group were analyzed. Output: /config/schemas/group-synthesis-output.json
6. **HYPOTHESIZE** (`agents/hypothesis.md`) — sequential, after all channel + group synthesis agents complete
7. **TOP SYNTHESIZE** (`agents/cross-channel/synthesis.md`) — conditional, only if 2+ channel groups are active. Consumes group summary cards.
8. **FORMAT** — Select template (anomaly-alert / period-comparison / weekly-report), render output
9. **MEMORY UPDATE** — append new baselines, log decisions to decisions-log.md, update known issues

## Data Rules
- All inputs go to /data/input/
- Only validated data (QC passed) is used for analysis
- All monetary values in USD
- Dates: YYYY-MM-DD internally, DD-MM-YYYY in user-facing output
- NA (North America, ~80% of business) and INTL (~20%) always reported separately, then blended
- Screenshots: extracted values tagged with [FROM SCREENSHOT]
- Every numeric claim must trace to a source file. No hallucinated numbers.

## Agent Invocation Rules
- When new files appear in /data/input/, ALWAYS run `python scripts/preprocess.py` then `python scripts/validate_data.py`
- Or use `python run_analysis.py` which handles the full pipeline automatically
- Orchestrator determines which channel agent(s) to invoke based on query keywords (with LLM fallback for unmatched queries)
- Channel agents run as parallel sub-agents, each receiving only their own prompt + relevant config (context isolation)
- Each channel agent must output structured JSON conforming to /config/schemas/channel-output.json
- Group synthesis agents run in parallel (one per group with 2+ active channels), output per /config/schemas/group-synthesis-output.json
- Hypothesis agent runs sequentially after all channel + group synthesis agents complete
- Top-level synthesis runs only when 2+ channel groups are active
- After every analysis run, update relevant memory files
- ICE-scored actions auto-logged to /memory/decisions-log.md

### Synthesis Trigger Rules
| Condition | Group Synthesis | Top-Level Synthesis |
|-----------|----------------|---------------------|
| Single channel query | No | No |
| 2+ channels, same group | Yes (for that group) | No |
| 2+ channels, different groups | Yes (per group with 2+) | Yes |
| All channels / holistic query | Yes (all groups) | Yes |

## Output Standards
- Tables preferred over paragraphs
- Every table includes: metric | current period | prior period | delta % | delta $
- Traffic light system: GREEN (on/above plan), YELLOW (within 5%), RED (>5% below)
- Every insight must cite the source file and relevant data point
- Assumptions labeled explicitly
- Conflicting data sources flagged, never silently resolved

## Extension Protocol
To add a new channel or data source:
1. Create /data/schemas/{source}.yaml (data schema)
2. Add validation rules to /config/data-quality-rules.yaml
3. Add source signature to scripts/preprocess.py SOURCE_SIGNATURES
4. Add source rules to scripts/validate_data.py SOURCE_RULES_MAP
5. Add metric definitions to /config/metrics.yaml if new metrics needed
6. Add benchmarks to /config/benchmarks.yaml if available
7. Create /agents/{group}/{agent}.md (output must conform to /config/schemas/channel-output.json)
8. Assign to a channel group in run_analysis.py CHANNEL_GROUPS and CHANNEL_AGENT_MAP
9. Update /agents/orchestrator.md routing table
10. Add routing entry to run_analysis.py ROUTING_TABLE and FILE_PREFIX_MAP
11. Create /memory/baselines/{channel}.md
12. Test with real data end-to-end: `python run_analysis.py --channels {channel}`
13. Log change in /prompts/changelog.md

To add a new channel group:
1. Add group to GROUP_CHANNELS and GROUP_SYNTHESIS_MAP in run_analysis.py
2. Create /agents/{group}/synthesis.md (output per /config/schemas/group-synthesis-output.json)
3. Create /agents/{group}/ directory with channel agents
4. Update /agents/orchestrator.md with group routing

## Memory Update Protocol
After each analysis run:
- Update /memory/baselines/{channel}-weekly-baselines.md with new rolling averages
- If actions were recommended and user confirms, log to /memory/decisions-log.md
- If external factors discovered (storms, outages, algo updates), add to /memory/known-issues.md
- If budget or promo calendar changes noted, update /memory/context.md

## Workflow Orchestration

### 1. Plan Node Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately - don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution

### 3. Self-Improvement Loop
- After ANY correction from the user: update tasks/lessons.md with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project

### 4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes - don't over-engineer
- Challenge your own work before presenting it

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests - then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how

## Task Management
- **Plan First:** Write plan to tasks/todo.md with checkable items
- **Verify Plan:** Check in before starting implementation
- **Track Progress:** Mark items complete as you go
- **Explain Changes:** High-level summary at each step
- **Document Results:** Add review section to tasks/todo.md
- **Capture Lessons:** Update tasks/lessons.md after corrections

## Core Principles
- **Simplicity First:** Make every change as simple as possible. Impact minimal code.
- **No Laziness:** Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact:** Changes should only touch what's necessary. Avoid introducing bugs.
