# screencraft: Version 1 build plan

## What it does
Input: a Figma screenshot (+ optional close-ups), the target route, the frame size if known, and the page type (app screen = fits the window, only inner panels scroll; content page = the page scrolls).
Output: the screen built inside the existing project, matching the design at the reference size, responsive from 320px to 2560px, with calm motion, every state (loading, empty, error, success), plain-language messages, and a report.

## Flow (every run)
1. Inputs.
2. Project understanding: read the saved profile (.claude/screencraft/profile.md in the project). If it is missing, or its key-file fingerprints changed, scan the project (or only the changed part) and save it.
3. Safety start: fingerprint every shared file and start the change log.
4. Study the screenshot with scripts: scale, grid, tiles, boxes, gaps, fonts, icons, colours. Write the spec sheet, including for each element its priority (primary / secondary / tertiary), its layout pattern and its small-screen plan (keep / stack / collapse / move behind a labelled button / remove decoration).
5. Clarity check: if anything is unclear, send a copy of the screenshot with numbered red boxes and one specific question per box, and WAIT for the user's answer before building.
6. Questions, only if any: new packages (name, why, size, the alternative if the user says no), shared-file changes, missing tokens or assets, all in one message. If there is nothing to ask, show the plan in 5 to 15 lines and continue WITHOUT waiting.
7. Build: skeleton -> details -> every state -> responsive pass -> calm motion pass. New code only in the screen's own files.
8. Self-check (in a helper sub-agent when available): pixel compare per region (max 5 rounds, stop early), the 14-width audit + 20px sweep + clicking every hidden-content trigger + spacing / tap-size / input / jargon checks + a reduced-motion run, the hardcoded-value scan, the project's lint / typecheck / build, and the shared-file fingerprint check.
9. Report, then update the lessons.

## Hard rules
- Never run any git command (no status, diff, log, branch, add, commit, stash, checkout, reset). Git belongs to the user.
- Never install a package into the project without the user's explicit yes. Check what is already installed first.
- Shared files are read-only: global CSS, theme and tokens, Tailwind config, components/ui (or the project's shared component folder), root layout and app shell, API client, global store, auth, shared types, package.json, lockfiles, env and build config. Changing one needs the user's yes.
- Reuse existing components, tokens, icons, utilities and patterns. Copy the codebase's habits.
- End users never see developer words. Developers still get the real error.
- Measure, don't guess. Ask when unclear.
- Don't fix old code you happen to notice: list it in the report under "Things I noticed".

## Per-project files the skill writes (inside the project)
.claude/screencraft/: profile.md, tokens.json, fingerprints.json, change-log.md, lessons.md, lessons-archive.md, screens/<screen>/ (spec.md, report.md, images). Tell the user once that these exist; whether to commit them is the user's choice.

## Skill files (Version 1)
- SKILL.md (Prompt 9)
- references/: safety-rules.md, token-budget.md (P1) | project-discovery.md, tokens-and-reuse.md (P2) | screenshot-analysis.md, clarity-check.md, spec-template.md (P3) | responsive-core.md, playbook-navigation.md, playbook-layout-sections.md, playbook-cards-grids.md, playbook-tables-lists.md, playbook-forms.md, playbook-overlays.md, playbook-media-content.md (P4) | build-rules.md, motion.md (P5) | errors-and-states.md (P6) | verification.md, checker-brief.md (P7) | report-and-lessons.md, report-template.md (P8)
- scripts/: setup_tools.py, fingerprint.py (P1) | extract_tokens.py, match_tokens.py, scan_code.py (P2) | measure_screenshot.py, grid_overlay.py, detect_boxes.py, sample_colors.py, mark_unclear.py (P3) | visual_compare.mjs, layout_audit.mjs (P7) | lessons_check.py (P8)
- assets/: tools-path.txt (P1), jargon-words.txt (P6), skill-lessons.md (P8)

## Token budget rules
- SKILL.md under about 300 lines / 5k tokens. References are split by topic and loaded only when needed; playbooks are loaded only for element types present on the screen.
- Scripts do the heavy work and print short summaries. Script code is never read during a run.
- While fixing, reports list the top 20 problems, grouped. The FINAL check lists every problem.
- Images: one full side-by-side at the start and at the end; crops of mismatched regions while fixing; full screenshots only for failed widths + 360, 768 and 1536; one contact-sheet image of all widths at the end. Measurements always come from the full-resolution originals; resized copies are only for overview looks.
- The profile and lessons are saved and reused; the profile re-scans only the parts whose fingerprints changed.
- Edit with targeted edits; don't re-read files just written; trim command output to errors.
- Stop fixing when every region passes (default 95% match per region) and there are zero errors.
- "quick" mode only when the user types "quick": 1 compare round, 6 widths.

## Lessons rules
Max about 60 lines, grouped by topic, with a General section that always loads. Merge similar lessons but keep every exact value. Lessons that held on 3+ screens graduate to profile rules (and the report says so). Repeated mistakes become tested script checks. One-time notes move to lessons-archive.md (never loaded, searched only when a similar problem appears). Show the user the list before anything is archived or removed.

## Done criteria for Version 1
On 3 real screens: at least 95% match per region at the reference size, zero audit errors at every width, no shared file changed without a yes, no package installed without a yes, the project build passes, and token use is recorded.

## Later versions (do not build now)
v2: component registry, API contract file, keyboard and form checks, state screenshots, fake-failure tests, slow-network test, Indian formats + app-wording check, Safari/Firefox runs, HTML visual report.
v3: update mode, Lighthouse, SEO, axe-core, dark-mode screenshots, handover note, generated tests.
