# Decisions Log

Tracks recommended actions from analyses and their outcomes.
Auto-populated by run_analysis.py when ICE-scored actions are generated.
Manually updated when outcomes are known.

## Format
| Date | Analysis Source | Decision Made | Expected Outcome | Actual Outcome | Status |
|------|---------------|---------------|-----------------|----------------|--------|

## How to Update
- **Auto-populated**: When run_analysis.py generates ICE-scored actions, top 5 are logged here with Status = "Open"
- **Manual update**: After implementing a recommended action, update "Actual Outcome" and set Status to:
  - "Confirmed" — action taken, outcome matched expectations
  - "Partial" — action taken, outcome partially matched
  - "Missed" — action taken, expected outcome did not materialize
  - "Reversed" — action taken but reversed due to negative results
  - "Declined" — action was recommended but not taken (note reason)
- **Feedback loop**: Hypothesis agent checks this log to learn from past decisions
