#!/usr/bin/env python3
"""screencraft fingerprint tool (Python standard library only).

Commands:
  snapshot <project>
      Hash every shared file (list from .claude/screencraft/profile.md section
      "## Shared files", else a built-in default list) plus the key files used
      to detect a stale profile. Writes .claude/screencraft/fingerprints.json.
  verify <project>
      Re-hash and print ONLY shared files that were changed, added or removed.
      Exit code 0 = no changes, 1 = changes found, 2 = no snapshot.
  stale <project>
      Compare per-section hashes of profile.md "## Key files" with the last
      snapshot; print the profile sections to re-scan. Run it BEFORE snapshot.
  log <project> --file <path> --action created|edited --why "..."
      Append one line to .claude/screencraft/change-log.md.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path

SC_DIR = Path(".claude") / "screencraft"

# Folders never scanned.
IGNORE_DIRS = {
    "node_modules", ".git", ".hg", ".svn", ".next", ".nuxt", ".svelte-kit", ".turbo",
    ".cache", ".parcel-cache", ".vercel", ".netlify", ".output", ".expo", ".angular",
    "dist", "build", "out", "coverage", "storybook-static", "vendor", ".venv", "venv",
    "__pycache__", ".idea", ".vscode", ".claude", ".yarn", ".pnpm-store",
}

# Default shared-file globs (used when the profile has no "## Shared files" section).
DEFAULT_SHARED = [
    # global CSS
    "**/globals.css", "**/global.css", "src/index.css", "src/styles/**", "styles/**",
    "app/styles/**", "src/app/styles/**", "src/assets/styles/**",
    # theme and tokens
    "**/theme.{ts,tsx,js,jsx,mjs,cjs,json,css,scss}", "**/tokens.{ts,js,mjs,cjs,json,css,scss}",
    "src/theme/**", "theme/**", "src/tokens/**",
    # tailwind / postcss
    "tailwind.config.*", "postcss.config.*",
    # shared components
    "components/ui/**", "src/components/ui/**", "app/components/ui/**",
    "src/shared/**", "src/common/**", "packages/ui/**",
    # root layout and app shell
    "app/layout.*", "src/app/layout.*", "pages/_app.*", "pages/_document.*",
    "src/pages/_app.*", "src/pages/_document.*", "src/App.*", "src/main.*",
    "src/index.{ts,tsx,js,jsx}", "app/root.*", "src/root.*", "src/routes/__root.*",
    "app.vue", "src/App.vue", "src/app/app.component.*", "src/routes/+layout.*",
    # API client
    "src/lib/api.*", "lib/api.*", "src/api/client.*", "src/services/api.*",
    "src/lib/axios.*", "lib/axios.*", "src/lib/fetcher.*", "src/utils/api.*",
    # global store
    "src/store/**", "src/stores/**", "store/**", "stores/**", "src/redux/**",
    # auth
    "src/auth/**", "auth/**", "src/lib/auth.*", "lib/auth.*", "auth.{ts,js}",
    "middleware.{ts,js}", "src/middleware.{ts,js}",
    # shared types
    "src/types/**", "types/**", "src/@types/**",
    # packages, lockfiles, env
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb",
    "bun.lock", ".env", ".env.*",
    # build config
    "next.config.*", "vite.config.*", "vitest.config.*", "tsconfig*.json",
    "jsconfig.json", "webpack.config.*", "babel.config.*", ".babelrc",
    ".eslintrc*", "eslint.config.*", ".prettierrc*", "prettier.config.*",
    "components.json", "nuxt.config.*", "angular.json", "svelte.config.*",
    "astro.config.*", "remix.config.*", "app.json", "app.config.*",
]

# Key files whose change means the profile may be stale.
KEY_FILES = [
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb",
    "bun.lock", "tsconfig.json", "jsconfig.json", "tailwind.config.*",
    "postcss.config.*", "components.json", "next.config.*", "vite.config.*",
    "nuxt.config.*", "angular.json", "svelte.config.*", "astro.config.*",
    "remix.config.*", "app.json", "app.config.*",
]

# Top-level source areas; their file LISTS (not contents) are hashed, so the
# profile can re-scan only the area whose structure changed.
AREA_ROOTS = ["src", "app", "components", "lib", "pages", "styles", "hooks", "utils"]


# ---------------------------------------------------------------- helpers
def _expand_braces(pat: str) -> list[str]:
    m = re.search(r"\{([^{}]*)\}", pat)
    if not m:
        return [pat]
    out = []
    for opt in m.group(1).split(","):
        out.extend(_expand_braces(pat[: m.start()] + opt + pat[m.end():]))
    return out


def _glob_to_regex(pat: str) -> re.Pattern:
    """Glob with ** support. '*' never crosses '/'. Patterns without '/' match at root only,
    unless they start with '**/'."""
    i, out = 0, ""
    while i < len(pat):
        if pat.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pat.startswith("**", i):
            out += ".*"
            i += 2
        elif pat[i] == "*":
            out += "[^/]*"
            i += 1
        elif pat[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pat[i])
            i += 1
    return re.compile(r"\A" + out + r"\Z", re.IGNORECASE if os.name == "nt" else 0)


def compile_patterns(patterns: list[str]) -> list[re.Pattern]:
    regs = []
    for p in patterns:
        p = p.strip().replace("\\", "/")
        while p.startswith("./") or p.startswith("/"):
            p = p[2:] if p.startswith("./") else p[1:]
        for e in _expand_braces(p):
            regs.append(_glob_to_regex(e))
    return regs


def walk_files(root: Path) -> list[str]:
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
        for f in filenames:
            files.append(f if rel_dir == "." else f"{rel_dir}/{f}")
    return sorted(files)


def match(files: list[str], patterns: list[str]) -> list[str]:
    regs = compile_patterns(patterns)
    return [f for f in files if any(r.match(f) for r in regs)]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_profile_list(project: Path) -> list[str] | None:
    """Return the bullets under '## Shared files' in profile.md, or None."""
    prof = project / SC_DIR / "profile.md"
    if not prof.is_file():
        return None
    items, inside = [], False
    for line in prof.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("## "):
            inside = line[3:].strip().lower().startswith("shared files")
            continue
        m = re.match(r"\s*[-*]\s+(.+)$", line) if inside else None
        if m:
            text = m.group(1)
            # "- `path` note", "- Label: `a`, `b`" (every backticked glob) or "- path note"
            ticks = re.findall(r"`([^`]+)`", text)
            items.extend(t.strip() for t in ticks) if ticks else items.append(text.split()[0])
    return items or None


def read_profile_sections(project: Path) -> dict[str, list[str]]:
    """Bullets under '## Key files' in profile.md: '- <Section>: `glob`, `glob`' -> {section: [globs]}."""
    prof = project / SC_DIR / "profile.md"
    if not prof.is_file():
        return {}
    out, inside = {}, False
    for line in prof.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("## "):
            inside = line[3:].strip().lower().startswith("key files")
            continue
        m = re.match(r"\s*[-*]\s+([^:]+):\s*(.+)$", line) if inside else None
        if m:
            globs = re.findall(r"`([^`]+)`", m.group(2)) or [g.strip() for g in m.group(2).split(",")]
            out[m.group(1).strip()] = [g for g in globs if g]
    return out


def section_hashes(root: Path, files: list[str], sections: dict[str, list[str]]) -> dict[str, str]:
    out = {}
    for name, globs in sections.items():
        hit = sorted(match(files, globs))
        h = hashlib.sha256()
        for f in hit:
            h.update(f"{f}:{sha256(root / f)}\n".encode())
        out[name] = h.hexdigest()
    return out


def area_hashes(root: Path, files: list[str]) -> dict[str, str]:
    out = {}
    for area in AREA_ROOTS:
        listed = [f for f in files if f.startswith(area + "/")]
        if listed:
            out[area] = hashlib.sha256("\n".join(listed).encode()).hexdigest()
    return out


def project_dir(arg: str) -> Path:
    p = Path(arg).expanduser().resolve()
    if not p.is_dir():
        sys.exit(f"ERROR: project folder not found: {p}")
    return p


def now() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- commands
def cmd_snapshot(a) -> int:
    root = project_dir(a.project)
    prof_list = read_profile_list(root)
    patterns = prof_list or DEFAULT_SHARED
    files = walk_files(root)
    shared = match(files, patterns)
    keys = match(files, KEY_FILES)
    data = {
        "created": now(),
        "source": "profile" if prof_list else "default",
        "patterns": patterns,
        "shared": {f: sha256(root / f) for f in shared},
        "key_files": {f: sha256(root / f) for f in keys},
        "areas": area_hashes(root, files),
        "sections": section_hashes(root, files, read_profile_sections(root)),
    }
    out = root / SC_DIR / "fingerprints.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Snapshot saved: {out.relative_to(root).as_posix()}")
    print(f"  shared files: {len(shared)} (list from {data['source']})")
    print(f"  key files: {len(keys)}  areas: {', '.join(data['areas']) or 'none'}")
    return 0


def cmd_verify(a) -> int:
    root = project_dir(a.project)
    fp = root / SC_DIR / "fingerprints.json"
    if not fp.is_file():
        print("ERROR: no snapshot. Run: fingerprint.py snapshot <project>")
        return 2
    old = json.loads(fp.read_text(encoding="utf-8"))
    before: dict = old.get("shared", {})
    current = match(walk_files(root), old.get("patterns", DEFAULT_SHARED))
    changed, added = [], []
    for f in current:
        if f not in before:
            added.append(f)
        elif sha256(root / f) != before[f]:
            changed.append(f)
    cur = set(current)
    removed = [f for f in before if f not in cur]
    total = len(changed) + len(added) + len(removed)
    if not total:
        print(f"OK: no shared file changed ({len(before)} checked)")
        return 0
    print(f"SHARED FILES CHANGED: {len(changed)} changed, {len(added)} added, {len(removed)} removed")
    for tag, lst in (("CHANGED", changed), ("ADDED", added), ("REMOVED", removed)):
        for f in lst:
            print(f"  {tag:<8} {f}")
    return 1


def cmd_stale(a) -> int:
    """Which profile sections need a re-scan. Run BEFORE snapshot (snapshot resets the baseline)."""
    root = project_dir(a.project)
    fp = root / SC_DIR / "fingerprints.json"
    if not (root / SC_DIR / "profile.md").is_file():
        print("STALE: no profile.md -> full discovery")
        return 1
    if not fp.is_file():
        print("STALE: no snapshot -> check the profile by hand, then run snapshot")
        return 1
    old = json.loads(fp.read_text(encoding="utf-8"))
    if not old.get("sections"):
        print("UNKNOWN: snapshot has no section hashes (taken before profile had '## Key files'); run snapshot")
        return 1
    files = walk_files(root)
    now_h = section_hashes(root, files, read_profile_sections(root))
    stale = [name for name, h in now_h.items() if old["sections"].get(name) != h]
    keys_now = {f: sha256(root / f) for f in match(files, KEY_FILES)}
    keys_old = old.get("key_files", {})
    key_changed = sorted(f for f in set(keys_now) | set(keys_old) if keys_now.get(f) != keys_old.get(f))
    areas_changed = sorted(k for k, v in area_hashes(root, files).items() if old.get("areas", {}).get(k) != v)
    if not stale and not key_changed:
        print(f"OK: profile fresh ({len(now_h)} sections checked)" +
              (f"; new/removed files in: {', '.join(areas_changed)}" if areas_changed else ""))
        return 0
    if stale:
        print("STALE sections (re-scan only these): " + ", ".join(stale))
    if key_changed:
        print("Key files changed: " + ", ".join(key_changed))
    if areas_changed:
        print("New/removed files in: " + ", ".join(areas_changed))
    return 1


def cmd_log(a) -> int:
    root = project_dir(a.project)
    p = Path(a.file).expanduser()
    if p.is_absolute():
        try:
            p = p.resolve().relative_to(root)
        except ValueError:
            pass
    rel = p.as_posix()
    why = " ".join(a.why.split()).replace("|", "/")
    log = root / SC_DIR / "change-log.md"
    log.parent.mkdir(parents=True, exist_ok=True)
    new = not log.is_file()
    with open(log, "a", encoding="utf-8") as fh:
        if new:
            fh.write("# screencraft change log\n\n| When | Action | File | Why |\n|---|---|---|---|\n")
        fh.write(f"| {now()} | {a.action} | {rel} | {why} |\n")
    print(f"Logged: {a.action} {rel}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="screencraft shared-file fingerprints and change log")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot", help="hash shared + key files")
    s.add_argument("project")
    s.set_defaults(fn=cmd_snapshot)
    v = sub.add_parser("verify", help="print shared files changed/added/removed")
    v.add_argument("project")
    v.set_defaults(fn=cmd_verify)
    st = sub.add_parser("stale", help="list profile sections whose key files changed (run before snapshot)")
    st.add_argument("project")
    st.set_defaults(fn=cmd_stale)
    lg = sub.add_parser("log", help="append a line to change-log.md")
    lg.add_argument("project")
    lg.add_argument("--file", required=True)
    lg.add_argument("--action", required=True, choices=["created", "edited"])
    lg.add_argument("--why", required=True)
    lg.set_defaults(fn=cmd_log)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
