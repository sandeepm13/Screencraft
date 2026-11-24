# Safety rules (start and end of every run)

Scripts live in the skill folder: `<skill>/scripts/`. Run them; never read their code during a run.

## Never
- Never run any git command (status, diff, log, branch, add, commit, stash, checkout, reset, anything). Git belongs to the user.
- Never install, remove or upgrade a package in the project without the user's explicit yes.
- Never touch, delete or regenerate a lockfile. Never mix package managers.
- Never edit a shared file without the user's explicit yes (list below).
- Never fix old code you happen to notice. List it in the report under **Things I noticed** (file, line, one sentence).

## START checklist

1. **Package manager.** Detect from the lockfile in the project root:

   | Lockfile | Manager |
   |---|---|
   | `package-lock.json` | npm |
   | `pnpm-lock.yaml` | pnpm |
   | `yarn.lock` | yarn |
   | `bun.lockb` or `bun.lock` | bun |

   - Also check `"packageManager"` in package.json. If it disagrees with the lockfile, do not guess.
   - Two lockfiles, or none: do not guess. Note it, and ask before any install. Use the same manager for every script run (`pnpm run build`, not `npm run build`).
2. **What is installed.** Read `dependencies` and `devDependencies` in package.json before proposing anything new. Prefer, in order: something already installed -> a small local helper in the screen's files -> a new package (needs a yes).
3. **Shared-files list.** Build it (see below), save it in the profile under `## Shared files`, then run:
   `python <skill>/scripts/fingerprint.py snapshot <project>`
4. **Change log.** Every file you create or edit, log it right after the edit:
   `python <skill>/scripts/fingerprint.py log <project> --file <path> --action created|edited --why "..."`
5. **Collect all questions into ONE message** (packages, shared-file changes, missing tokens or assets). If there are none, show the plan and continue without waiting.

## Building the shared-files list
Start from these categories and record the real paths that exist in this project (globs allowed, `- ` bullets, one category per bullet with every path in backticks, e.g. `- Styles: \`src/styles/**\`, \`tailwind.config.js\``, under `## Shared files` in `.claude/screencraft/profile.md`; `fingerprint.py` reads exactly that section):

- Global CSS: `globals.css`, `index.css`, `src/styles/**`, `styles/**`
- Theme and tokens: `theme.*`, `tokens.*`, `src/theme/**`, CSS variable files
- Tailwind / PostCSS config: `tailwind.config.*`, `postcss.config.*`
- Shared component folder: `components/ui/**` (shadcn), or whatever folder most screens import from (`src/shared/**`, `src/common/**`, `packages/ui/**`)
- Root layout and app shell: `app/layout.*`, `pages/_app.*`, `pages/_document.*`, `src/App.*`, `src/main.*`, `app/root.tsx`, router root, sidebar/header shell
- API client: `lib/api.*`, `services/api.*`, axios/fetch wrapper, generated clients
- Global store: `store/**`, `stores/**`, `redux/**`, context providers at the root
- Auth: `auth/**`, `lib/auth.*`, `middleware.*`
- Shared types: `types/**`, `@types/**`
- `package.json`, every lockfile, `.env*`
- Build config: `next.config.*`, `vite.config.*`, `tsconfig*.json`, `webpack.config.*`, `babel.config.*`, eslint and prettier config, `components.json`, framework configs

If the profile has no list yet, `fingerprint.py` uses a built-in default list close to the one above. A file is shared if more than one screen depends on it; when unsure, treat it as shared.

## Asking for a package (exact format)
One block per package, all in the same message:

```
Package: <name>@<version>
For: <what it does on THIS screen, one sentence>
Size: <min> KB minified, <gz> KB gzipped (bundlephobia or package data)
Weekly downloads: <n>   Last publish: <date>
Goes in: dependencies | devDependencies
If you say no: <exact alternative, e.g. "a 40-line local hook in the screen folder" or "the existing X component">
Install command: <manager> add <name>   (I will run it only after your yes)
```

## Asking for a shared-file change (exact format)

```
File: <path>
Change:
  - <old line>
  + <new line>
Why: <one sentence, what the screen needs>
Could affect: <other screens/components that import it, or "nothing else found">
Local alternative: <wrapper component | className on the instance | local variant in the screen folder>
I recommend: <the change | the local alternative>, because <reason>
```

No yes = use the local alternative.

## Allowed small edits outside the screen folder (no question needed)
- Registering the route (router file, route config, or page file in the routes folder).
- Adding a nav link to the existing nav list, in the existing style.

These must be the smallest possible edit, logged in the change log, and listed in the report. If the router or nav file is in the shared list as a layout/shell file, still allowed only for that one-line registration; anything bigger needs a yes.

## END checklist
1. `python <skill>/scripts/fingerprint.py verify <project>`
   - Nothing printed except the OK line = done.
   - Any shared file changed / added / removed that the user did not approve: revert your edit to it (you know the edit from the change log), re-run verify. Never use git to revert.
   - A changed file you did not touch (user edited while you worked): do not revert; mention it in the report.
2. Lockfile and package.json unchanged unless an install was approved.
3. Every change-log line appears in the report (created / edited / allowed small edits).
4. Report has **Things I noticed** for old problems you saw and did not fix (or "None").
