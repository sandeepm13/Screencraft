# Token budget

Spend tokens on looking and building, not on re-reading.

## Loading
- Load a reference only when its step starts. Load playbooks only for element types on this screen.
- Never read script code. Run scripts; use `--help` if unsure of options.
- Read the saved profile and lessons instead of re-scanning. Re-scan only the parts whose fingerprints changed.

## Editing and output
- Targeted edits, not whole-file rewrites. Don't re-read a file you just wrote.
- Trim command output to errors: pipe build/lint/typecheck through `tail`/filters; never paste full logs.
- Scripts print short summaries; ask them for detail only for the failing item.

## Problem lists
- While fixing: top 20 problems, grouped by type.
- Final check: every problem, no cap.

## Images
- Start and end: one full side-by-side each.
- While fixing: crops of mismatched regions only.
- Full screenshots only for failed widths plus 360, 768 and 1536.
- End: one contact-sheet image of all widths.
- Measure on full-resolution originals. Resized copies are for overview looks only.

## When to stop
- Every region at or above the pass mark (default 95% per region) and zero errors: stop.
- Max 5 compare rounds; stop early when passing.
- `quick` mode (only if the user types "quick"): 1 compare round, 6 widths.

## Record
- Note token use for the run in the report.
