# Cost

> Status: measurement starts in Phase 1.

## Plan

- Compute cost per model call from provider-reported token usage × a versioned price table in code.
- Aggregate per investigation run.
- Primary metric: **cost per successful task** = total cost of all runs ÷ runs that passed evals.
  (Cost of failed runs is included — failures are not free.)
- First comparison: workflow (1a) vs agent loop (1b).
