# Tokens and reuse

Use what the project already has. New code never adds a hex, a pixel value off the scale, a second palette,
a second icon set, or a copy of a shared component. Project rules in `profile.md` (`## Project rules`) are
binding; where they are stricter than this file, they win.

## 1. Colours
Order of preference, always:
1. A project token, used by its Tailwind class (`bg-primary`, `text-muted-foreground`) or, in CSS files,
   by its variable (`var(--primary)`; with alpha: `rgb(var(--primary-rgb) / 0.1)` if channel vars exist).
2. The same token at an opacity over its real background (`bg-primary/10`).
3. Ask the user. Never invent a token, never hardcode the sampled hex, never start a second palette.

Matching sampled colours:
```
python <skill>/scripts/match_tokens.py --tokens <project>/.claude/screencraft/tokens.json \
  --colors "#0a5f38,#e7efeb" --background "#ffffff"
```
| Delta E 2000 | Do |
|---|---|
| under 2 | use the token, no comment |
| 2 to 5 | use the token, list it in the report ("#0b6239 -> primary, dE 3.1") |
| over 5 | the script tries token-at-opacity over `--background`; under 5 there -> use it (mention if 2-5) |
| still over 5 | `ASK`: one question per colour, all in the single questions message (format below) |

- Pass the colour the element actually sits on as `--background` (card, muted panel), not always the page.
- When the script prints `better: primary/10 ...` for a 2-5 match, choose by meaning, not by the smaller dE.
- `note: Tailwind default slate-500 matches`: default-palette colours are not project tokens. Use one only if
  the profile says the project allows them; otherwise ask, offering the nearest project token.
- Same hex, several names: pick by meaning. Text -> `foreground` / `text-*` / `*-foreground`; surfaces ->
  `background` / `card` / `muted` / `popover`; lines -> `border` / `input`; focus -> `ring`; status ->
  `destructive` / `success` / `warning` / `info`; brand action -> `primary`. Never use raw palette tiers the
  profile marks "do not consume" when a semantic name exists.
- Arbitrary opacity (`/[0.13]`) only if the project allows arbitrary values; else the nearest 5% step.

Ask format (one block per colour, inside the one questions message):
```
Colour: #64748b (secondary text under the card title)
No project token within dE 5. Nearest: info (dE 15), --info-strong (dE 19).
Options: (a) text-muted-foreground (closest in meaning)  (b) a token you name  (c) keep exact: needs a new token (your call)
```

## 2. Sizes, type, radius, shadows, z-index
- Spacing, radius, font size and shadow come from the scales in `tokens.json` (`scales.*`, px values given).
- Measured value on a scale step -> that class. Within 2px of a step -> snap and list it in the report.
  Further off -> mention it; ask only if it changes the look visibly (e.g. a 36px gap vs 32/40).
- Font sizes use the type scale (custom names first, e.g. `text-h2`, then defaults). Never `text-[13px]`.
- z-index: the project's scale/layers only; overlays use the existing dialog/popover components, which
  already sit on the right layer.
- Breakpoints: the project's (`scales.screens`), never new ones.

## 3. Reuse before writing
Search in this order and say what you searched (file globs / grep terms) in the plan or report:
1. Shared components (`profile.md ## Components`): exact variant and size first.
2. Feature-level shared pieces (status cards, page headers, empty states, tables) used by other screens.
3. Icons: only the installed set the profile names (sizes by class, `aria-hidden` when decorative, an
   accessible label on icon-only buttons). An icon missing from the set -> nearest icon from the same set,
   mention it; never add a second icon library.
4. Utilities: `cn()` for every conditional class; existing formatters (`formatDate`, `formatDuration`,
   currency/number helpers) and hooks (API hooks, debounce, media query). Never re-implement one.
5. Patterns: how sibling screens do loading, empty, error, toasts, confirm dialogs. Copy that.

Record in the report: `Reused: Button (cta, lg), Card, StatusToast via addToast, formatDate, ArrowRight icon`.

## 4. Variants without editing shared components
Shared component files are read-only (see `safety-rules.md`). Options, in order:
1. An existing variant / size / prop that gives the look.
2. `className` on the instance: layout first (margin, width, grid placement); visual tweaks only if the
   project's rules allow className overrides on primitives.
3. A local wrapper in the screen's own folder that composes the primitive:
   ```tsx
   // src/components/<feature>/<Feature>FilterChip.tsx
   import { Button, type ButtonProps } from "@/components/ui/button";
   import { cn } from "@/lib/utils";
   export function ReportsFilterChip({ className, ...props }: ButtonProps) {
     return <Button variant="soft" size="compact" className={cn("min-w-20", className)} {...props} />;
   }
   ```
4. A new variant in the shared file: only with the user's yes (shared-file change format in
   `safety-rules.md`, recommend the local alternative unless several screens need it). No yes -> option 3.
Never copy a shared component's source into the screen and modify it.

## 5. Contrast (WCAG 2.2 AA)
- Text: 4.5:1. Large text (>= 24px, or >= 18.66px bold): 3:1.
- Non-text UI that must be seen (input borders, focus rings, icons that carry meaning, chart lines): 3:1
  against what they sit on. Disabled controls and pure decoration are exempt.
- Check every new text/background pair, including text on tinted panels and translucent overlays:
  `match_tokens.py --colors "<text hex>" --background "<bg hex>"` prints the ratio (alpha is composited).
- The design fails -> do not silently change it. Warn the user in the questions message (or the report if
  nothing else needs asking) with the numbers and a passing alternative from the tokens:
  `Caption text-subtle (#059669) on mint-50 = 3.7:1, fails AA for 14px text. Option: text-secondary (5.4:1).`
  Build what the user chooses; with no answer, use the passing token and say so in the report.

## 6. Dark mode
- `tokens.json` `themes.has_dark` false (profile: light only) -> no `dark:` classes, nothing to check.
- If the project has dark mode, every new colour use must work in both themes:
  - Use tokens whose `dark` value exists (or that switch through CSS variables); never a fixed hex/default
    colour that only suits one theme. Follow the project's habit: switching variables vs `dark:` pairs.
  - A token with `dark: null` in a dark-mode project -> check it reads on the dark background; if not, ask.
  - Run the contrast check for both themes (`--theme dark` with the dark background).
  - Shadows, borders, images with white edges and translucent overlays need a dark look too.

## 7. Checking your own code
- Before the self-check, run `python <skill>/scripts/scan_code.py <every file you created or edited>`.
  Every finding in new code gets fixed (or is a listed, approved exception). Findings in old code you did
  not write go to **Things I noticed**, not into a fix.
- Report a token section: tokens used, dE 2-5 mentions, opacity uses, snapped sizes, questions asked and
  answers, contrast warnings.
