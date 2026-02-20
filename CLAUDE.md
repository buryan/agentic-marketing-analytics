# Marketing Analytics Agent System

## Purpose
Agentic system for automated marketing analytics across Paid (SEM, Display, Affiliate) and SEO channels for an ecommerce marketplace. All analysis runs on imported data only (CSV, screenshots, exports). No API connections. All agents are .md prompt files. Claude reasons directly over data.

## Architecture
Hybrid Python + LLM agent system. The Python orchestrator (`run_analysis.py`) enforces the processing chain, manages context isolation, and enables parallel execution. LLM agents handle reasoning-heavy tasks (analysis, hypothesis, synthesis). Deterministic Python scripts handle mechanical tasks (preprocessing, data quality validation).

### Key Components
- **run_analysis.py** — Master orchestrator enforcing the 7-step chain
- **scripts/preprocess.py** — Deterministic file standardization (replaces LLM preprocessing)
- **scripts/validate_data.py** — Deterministic data quality validation with gate logic
- **agents/*.md** — LLM agent prompts for reasoning-heavy analysis
- **config/schemas/*.json** — Structured output contracts (channel-output, hypothesis-output, synthesis-output)
- **data/pipeline/** — Inter-agent communication via JSON files

### Standalone Pipelines (independent of agent chain)
- **run_display_halo.py** → Display Halo Effect analysis (Python + HTML)
- **run_sem_incrementality.py** → SEM Incrementality test analysis (Python + HTML)

## Processing Chain (mandatory order)
Every analysis request follows this exact sequence. Enforced by `run_analysis.py`. Never skip steps.

1. PREPROCESS (`scripts/preprocess.py`) — deterministic: standardize file names, columns, dates, split combined files
2. DATA QUALITY (`scripts/validate_data.py`) — deterministic: validate schema, completeness, sanity. Gate: FAIL = block, WARN = proceed with caveats
3. ORCHESTRATOR (`run_analysis.py` + `agents/orchestrator.md`) — classify query, select agent(s), set date range
4. CHANNEL AGENT(S) — **parallel** execution via sub-agents, each with isolated context (~8KB vs ~36KB). Output: structured JSON per /config/schemas/channel-output.json
5. HYPOTHESIS AGENT (`agents/hypothesis.md`) — sequential, explain WHY metrics moved, assign confidence
6. SYNTHESIS AGENT (`agents/cross-channel/synthesis.md`) — conditional (2+ channels), cross-channel view + contradictions + ICE-scored actions
7. MEMORY UPDATE — append new baselines, log decisions to decisions-log.md, update known issues

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
- Hypothesis agent runs sequentially after all channel agents complete
- Synthesis agent runs only when 2+ channel agents are invoked
- After every analysis run, update relevant memory files
- ICE-scored actions auto-logged to /memory/decisions-log.md

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
7. Create /agents/{category}/{agent}.md (output must conform to /config/schemas/channel-output.json)
8. Update /agents/orchestrator.md routing table
9. Add routing entry to run_analysis.py ROUTING_TABLE
10. Create /memory/baselines/{channel}.md
11. Test with real data end-to-end: `python run_analysis.py --channels {channel}`
12. Log change in /prompts/changelog.md

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
