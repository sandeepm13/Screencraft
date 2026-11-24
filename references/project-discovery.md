# Project discovery -> .claude/screencraft/profile.md

Goal: understand the project fast, write the facts once, reuse them on every run.
Read-only: never edit a project file, never run git, never install. Only `.claude/screencraft/` is written.

## When to run
1. No `profile.md` -> full discovery (all steps below), then `fingerprint.py snapshot`.
2. `profile.md` exists -> `python <skill>/scripts/fingerprint.py stale <project>` (BEFORE snapshot):
   - `OK: profile fresh` -> read the profile, skip discovery.
   - `STALE sections: A, B` -> redo only those steps, edit only those sections.
   - `Key files changed: package.json` -> redo Stack, Libraries, Scripts. Lockfile -> Stack.
   - `New/removed files in: src` -> redo Layout and routes only if routes/shell moved.
   Then run `snapshot` so the next run compares against the new state.

## Rules for the profile
- Facts and file paths, no essays. About 120 lines max. One line per fact where possible.
- Every fact comes from a file you looked at. Unknown = write `not found`, never guess.
- Counts beat adjectives: "lucide-react (310 files)" not "mostly lucide".
- Copy project instructions (CLAUDE.md, AGENTS.md, .cursorrules, CONTRIBUTING.md, README "conventions") into
  `## Project rules` as short bullets. They are binding. If one conflicts with a screencraft rule, the stricter
  one wins and the line says so (e.g. "variants go in the primitive file, but editing it still needs a yes").
- Do not copy the palette into the profile: `tokens.json` holds it. The profile says where tokens live and how
  to use them.

## Steps (each fills one profile section)

### 1. Stack
- `package.json`: name, framework + version, React/Vue version, TypeScript (`tsconfig.json`, `strict`), path
  aliases (`compilerOptions.paths`), Node version (`.nvmrc`, `engines`).
- Package manager: lockfile table in `safety-rules.md`. Also check the parent folder: a lockfile or
  `workspaces` there = monorepo; note it and which lockfile governs this folder.
- Framework and router:
  | Signal | Means |
  |---|---|
  | `next` + `app/` or `src/app/` with `layout.tsx` | Next App Router (server components by default) |
  | `next` + `pages/` or `src/pages/` with `_app.tsx` | Next Pages Router |
  | both | mixed: record which routes live where |
  | `vite` + `react` (+ `react-router`, `@tanstack/react-router`, `@tanstack/react-start`) | Vite SPA / TanStack; find the router root |
  | `@remix-run/*` or `react-router` v7 with `app/root.tsx`, `app/routes/` | Remix / RR7 framework mode |
  | `nuxt` / `vue` | Nuxt (`pages/`, `layouts/`, `app.vue`) / Vue SPA |
  | `@sveltejs/kit`, `astro`, `@angular/core` | SvelteKit, Astro, Angular |
  | only `.html` files | plain HTML: note the CSS and JS entry files |
- Project instructions files and their key rules -> `## Project rules`.

### 2. Styling
- Tailwind: version from `node_modules/tailwindcss/package.json` (else the range in package.json).
  v4 = `@import "tailwindcss"` + `@theme` in CSS, no config needed. v3 = `tailwind.config.*`.
- Other: CSS modules (`*.module.css` count), styled-components / emotion, SCSS, plain global CSS.
- Global CSS files and anything notable in them: component classes (`.btn-primary`, `.card`), Tailwind
  utilities redefined (extract_tokens warns), `!important` z-index hacks, global font imports.
- `cn()` / `clsx` / `twMerge` helper path.

### 3. Tokens
Run `python <skill>/scripts/extract_tokens.py <project>`. Write a summary from its output:
where colours are defined (file + how tiers chain), dark mode yes/no and how it switches (`.dark` class,
`data-theme`, media query), fonts (and how they load), custom spacing / radius / type / shadow / z-index /
breakpoint values, the opacity pattern (`bg-primary/10` works or not), default-palette use, warnings.

### 4. Components
- Library: shadcn (`components.json`, or hand-copied `components/ui/*` with cva + Radix), MUI, Chakra,
  Mantine, Ant, Headless UI, custom.
- List every shared component, one line each, with variants: read only the `cva(` block or the props type
  (`grep -n "cva(\|variant\|size" <file>`), not the whole file. Format:
  `Button (ui/button.tsx): variant default|outline|... ; size sm|lg|... ; shape pill`
- Feature-level shared pieces many screens reuse (status cards, empty states, page headers, tables).

### 5. Libraries (package.json + import counts)
Count imports, e.g. `grep -rl "from ['\"]lucide-react" src | wc -l`. Record each with its file count:
- Icons; animation (motion / framer-motion, tailwindcss-animate or tw-animate-css, GSAP, CSS keyframes in
  global CSS, smooth-scroll libs); does any `prefers-reduced-motion` handling exist?
- Feedback: toast (how to call it, where it is mounted), alert, dialog, confirm. Forbidden patterns
  (e.g. `window.alert`).
- Errors: error boundaries, `error.tsx` / `not-found.tsx` / `404.tsx` / `_error.tsx`, edge-case screens.
- Data: React Query / SWR / RTK Query / fetch / axios client (path, interceptors), where hooks live,
  query client defaults.
- Forms and validation (react-hook-form, formik, zod, yup, or none + local helpers).
- State (zustand, redux, jotai, context): store paths and what each holds.
- Auth, dates and formatters (`formatDate` etc.), charts, i18n.
- Installed but unused (0 imports): list them, so nobody "adds" a second icon set.

### 6. Layout and routes
- Router root and app shell: providers, global mounts (toasts, modals), what wraps every page.
- Shells/layouts and which pages use them (count imports of each).
- Where routes live, dynamic segment style (`[id]`), auth guard pattern (e.g. `getServerSideProps = requireAuth`).
- Where feature components, hooks, API hooks, types and utils live.
- Conventions copied from 1-2 representative screens: pick recent ones that follow the project rules
  (few hex / inline styles: `scan_code.py` shows it). Record file naming, component naming, export style,
  import alias, how loading / error / empty states are shown.

### 7. Wording
From the same 1-2 screens plus toasts and errors: heading case, button case and verbs, tone, message
pattern for success / failure, ellipsis character, numbers and dates format. 3-6 real examples in quotes.

### 8. Scripts
`package.json` scripts: dev (command + port), build, lint, typecheck (if missing: the command that works,
e.g. `npx tsc --noEmit`), test. Note if the build ignores type or lint errors, and known baseline error counts.

### 9. Shared files and Key files
- `## Shared files`: real paths per `safety-rules.md` categories, one `- ` bullet each, globs allowed.
  `fingerprint.py` reads exactly this section.
- `## Key files`: one bullet per profile section -> the globs whose change makes it stale.
  Format (parsed by `fingerprint.py stale`): `- Tokens: \`src/styles/globals.css\`, \`tailwind.config.js\``

## Profile template
```
# Project profile: <name>
Updated <YYYY-MM-DD> by screencraft. Facts only; tokens in tokens.json.

## Stack
## Project rules
## Styling
## Tokens
## Components
## Libraries
## Layout and routes
## Conventions
## Wording
## Scripts
## Shared files
## Key files
## Things I noticed
```
`Things I noticed`: old problems seen during discovery (file:line, one sentence). Never fix them.

## After writing
1. `python <skill>/scripts/fingerprint.py snapshot <project>`
2. Tell the user once that `.claude/screencraft/` exists and that committing it is their choice.
