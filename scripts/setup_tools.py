#!/usr/bin/env python3
"""screencraft tools setup. The skill's own tools live OUTSIDE every project, in one tools folder.

Tools: Python venv with Pillow, numpy, opencv-python; Node folder with playwright, pixelmatch,
pngjs; Playwright's Chromium (kept inside the tools folder via PLAYWRIGHT_BROWSERS_PATH).

Commands:
  check                 list installed / missing tools with approximate sizes (installs nothing)
  set-path <folder>     save the tools folder in assets/tools-path.txt (only after the user confirms)
  install --yes         install what is missing (only after the user says yes)
  paths                 print JSON with the tool locations, for other scripts

Default folder: D:\\screencraft-tools on Windows (fallback ~/.screencraft-tools if D: does not
exist), ~/.screencraft-tools elsewhere. The first time, the user must confirm it.
Exit codes: 0 = ready / ok, 2 = something missing, 3 = needs the user's confirmation, 1 = error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
PATH_FILE = SKILL_DIR / "assets" / "tools-path.txt"
IS_WIN = os.name == "nt"

# (distribution name, approx MB on disk)
PY_PKGS = [("Pillow", 12), ("numpy", 35), ("opencv-python", 95)]
NODE_PKGS = [("playwright", 10), ("pixelmatch", 0.1), ("pngjs", 0.5)]
VENV_MB, CHROMIUM_MB = 20, 300
PY_RANGE = ((3, 10), (3, 14))  # wheels for numpy/Pillow/opencv reliably exist here


# ---------------------------------------------------------------- locations
def default_dir() -> tuple[Path, str]:
    home = Path.home() / ".screencraft-tools"
    if not IS_WIN:
        return home, ""
    if Path("D:/").exists():
        return Path("D:/screencraft-tools"), ""
    return home, r"default D:\screencraft-tools not possible: drive D: not found"


def tools_dir() -> tuple[Path, bool, str]:
    """(folder, confirmed, note)."""
    if PATH_FILE.is_file():
        txt = PATH_FILE.read_text(encoding="utf-8").strip()
        if txt:
            return Path(txt).expanduser(), True, ""
    d, note = default_dir()
    return d, False, note


def layout(root: Path) -> dict:
    venv = root / "venv"
    py = venv / ("Scripts/python.exe" if IS_WIN else "bin/python")
    return {
        "tools_dir": str(root),
        "venv": str(venv),
        "python": str(py),
        "node_dir": str(root / "node"),
        "node_modules": str(root / "node" / "node_modules"),
        "browsers_path": str(root / "ms-playwright"),
    }


# ---------------------------------------------------------------- probes
def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def py_version(exe: str) -> tuple[int, int, int] | None:
    try:
        r = run([exe, "-c", "import sys;print('%d.%d.%d'%sys.version_info[:3])"], timeout=30)
        return tuple(int(x) for x in r.stdout.strip().split(".")) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def in_range(v) -> bool:
    return v is not None and PY_RANGE[0] <= v[:2] <= PY_RANGE[1]


def pick_python(forced: str | None) -> tuple[str | None, tuple | None]:
    """Base Python for the venv: --python, else newest installed in PY_RANGE, else current."""
    if forced:
        return forced, py_version(forced)
    cands = [sys.executable]
    if IS_WIN and shutil.which("py"):
        r = run(["py", "-0p"])
        cands += re.findall(r"([A-Za-z]:\\\S+python\.exe)", r.stdout)
    else:
        for m in range(PY_RANGE[1][1], PY_RANGE[0][1] - 1, -1):
            w = shutil.which(f"python3.{m}")
            if w:
                cands.append(w)
    found = [(py_version(c), c) for c in dict.fromkeys(cands)]
    good = sorted([f for f in found if in_range(f[0])], reverse=True)
    if good:
        return good[0][1], good[0][0]
    return sys.executable, py_version(sys.executable)


def venv_packages(py: Path) -> dict[str, str]:
    if not py.is_file():
        return {}
    code = (
        "import json,importlib.metadata as m\nout={}\n"
        f"for n in {[p for p, _ in PY_PKGS]!r}:\n"
        "    try: out[n]=m.version(n)\n    except Exception: pass\nprint(json.dumps(out))"
    )
    r = run([str(py), "-c", code], timeout=60)
    try:
        return json.loads(r.stdout) if r.returncode == 0 else {}
    except ValueError:
        return {}


def node_pkg(node_modules: Path, name: str) -> str | None:
    pj = node_modules / name / "package.json"
    if not pj.is_file():
        return None
    try:
        return json.loads(pj.read_text(encoding="utf-8")).get("version", "?")
    except ValueError:
        return "?"


def chromium_dirs(browsers: Path) -> list[str]:
    if not browsers.is_dir():
        return []
    return sorted(d.name for d in browsers.iterdir()
                  if d.is_dir() and d.name.startswith("chromium")
                  and (d / "INSTALLATION_COMPLETE").exists())


def cmd_version(name: str) -> str | None:
    exe = shutil.which(name)
    if not exe:
        return None
    try:
        r = run([exe, "--version"], timeout=30)
        return r.stdout.strip() or r.stderr.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None


def free_gb(p: Path) -> float | None:
    q = p
    while not q.exists() and q != q.parent:
        q = q.parent
    try:
        return shutil.disk_usage(q).free / 1e9
    except OSError:
        return None


def status(root: Path) -> dict:
    L = layout(root)
    py = Path(L["python"])
    pk = venv_packages(py)
    items = [("Python", "venv", py_version(str(py)) and "%d.%d.%d" % py_version(str(py)), VENV_MB)]
    items += [("Python", n, pk.get(n), mb) for n, mb in PY_PKGS]
    nm = Path(L["node_modules"])
    items += [("Node", n, node_pkg(nm, n), mb) for n, mb in NODE_PKGS]
    ch = chromium_dirs(Path(L["browsers_path"]))
    items.append(("Node", "Chromium (Playwright)", ", ".join(ch) or None, CHROMIUM_MB))
    return {"layout": L, "items": items}


# ---------------------------------------------------------------- commands
def fmt_mb(mb: float) -> str:
    return f"~{mb:.0f} MB" if mb >= 1 else "<1 MB"


def cmd_check(a) -> int:
    root, confirmed, note = tools_dir()
    if a.tools_dir:
        root, confirmed, note = Path(a.tools_dir).expanduser(), False, "given with --tools-dir"
    base, bver = pick_python(a.python)
    node_v, npm_v = cmd_version("node"), cmd_version("npm")
    st = status(root)

    print("screencraft tools check")
    flag = "confirmed" if confirmed else "NOT CONFIRMED - ask the user before saving"
    print(f"  Tools folder : {root}  ({flag})")
    if note:
        print(f"                 note: {note}")
    gb = free_gb(root)
    if gb is not None:
        print(f"  Free space   : {gb:.1f} GB")
    bv = "%d.%d.%d" % bver if bver else "unknown"
    warn = "" if in_range(bver) else "  WARNING: outside 3.10-3.14, wheels may be missing"
    print(f"  Base Python  : {bv} ({base}) - used to create the venv{warn}")
    print(f"  Node / npm   : {node_v or 'NOT FOUND'} / {npm_v or 'NOT FOUND'}")

    missing_mb, missing = 0.0, 0
    group = None
    for grp, name, ver, mb in st["items"]:
        if grp != group:
            print(f"  {grp}:")
            group = grp
        if ver:
            print(f"    OK       {name:<24} {ver}")
        else:
            print(f"    MISSING  {name:<24} {fmt_mb(mb)}")
            missing += 1
            missing_mb += mb
    if not node_v:
        print("  ERROR: Node.js is required (18+). Install it, then re-run check.")
    if missing:
        print(f"  Missing: {missing} item(s), about {missing_mb:.0f} MB on disk.")
        steps = [] if confirmed else ["confirm the folder, then: setup_tools.py set-path <folder>"]
        steps.append("after the user says yes: setup_tools.py install --yes")
        print("  Next: " + "; ".join(steps))
        return 2
    print("  READY: all tools installed.")
    return 0 if confirmed else 3


def cmd_set_path(a) -> int:
    p = Path(a.folder).expanduser().resolve()
    if p.exists() and not p.is_dir():
        print(f"ERROR: not a folder: {p}")
        return 1
    anchor = Path(p.anchor) if p.anchor else None
    if anchor and not anchor.exists():
        print(f"ERROR: drive {p.anchor} does not exist")
        return 1
    PATH_FILE.parent.mkdir(parents=True, exist_ok=True)
    PATH_FILE.write_text(str(p) + "\n", encoding="utf-8")
    print(f"Saved tools folder: {p}")
    print(f"  in {PATH_FILE}")
    return 0


def step(title: str, cmd: list[str], **kw) -> bool:
    print(f"- {title} ...", flush=True)
    r = run(cmd, **kw)
    if r.returncode != 0:
        tail = "\n".join((r.stdout + "\n" + r.stderr).strip().splitlines()[-15:])
        print(f"  FAILED ({r.returncode}):\n{tail}")
        return False
    print("  done")
    return True


def cmd_install(a) -> int:
    root, confirmed, _ = tools_dir()
    if not confirmed:
        print("NEEDS CONFIRMATION: tools folder not saved yet. Ask the user, then run set-path <folder>.")
        return 3
    st = status(root)
    todo = [(g, n, mb) for g, n, v, mb in st["items"] if not v]
    if not todo:
        print("Nothing to install: all tools present.")
        return 0
    if not a.yes:
        print(f"Would install into {root}:")
        for g, n, mb in todo:
            print(f"  {g:<7} {n:<24} {fmt_mb(mb)}")
        print(f"Total about {sum(mb for *_, mb in todo):.0f} MB. Ask the user; on yes run: install --yes")
        return 3
    if not shutil.which("node") or not shutil.which("npm"):
        print("ERROR: Node.js and npm are required. Install Node 18+ first.")
        return 1

    L = st["layout"]
    root.mkdir(parents=True, exist_ok=True)
    names = {n for _, n, _ in todo}
    ok = True

    py = Path(L["python"])
    if "venv" in names:
        base, bver = pick_python(a.python)
        print(f"Base Python {'%d.%d.%d' % bver if bver else '?'}: {base}")
        ok &= step("create venv", [base, "-m", "venv", L["venv"]])
    py_missing = [n for n, _ in PY_PKGS if n in names]
    if ok and py_missing:
        ok &= step("pip install " + " ".join(py_missing),
                   [str(py), "-m", "pip", "install", "--disable-pip-version-check", "-q", *py_missing])

    node_dir = Path(L["node_dir"])
    node_dir.mkdir(parents=True, exist_ok=True)
    pj = node_dir / "package.json"
    if not pj.is_file():
        pj.write_text(json.dumps({"name": "screencraft-tools", "private": True,
                                  "description": "screencraft skill tools (not a project)"}, indent=2),
                      encoding="utf-8")
    node_missing = [n for n, _ in NODE_PKGS if n in names]
    if node_missing:
        ok &= step("npm install " + " ".join(node_missing),
                   [shutil.which("npm"), "install", "--no-fund", "--no-audit", "--loglevel=error",
                    *node_missing], cwd=node_dir)
    if "Chromium (Playwright)" in names:
        cli = Path(L["node_modules"]) / "playwright" / "cli.js"
        env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=L["browsers_path"])
        ok &= step("playwright install chromium",
                   [shutil.which("node"), str(cli), "install", "chromium"], env=env)

    print()
    a.tools_dir, a.python = None, None
    rc = cmd_check(a)
    return 0 if ok and rc == 0 else 1


def cmd_paths(a) -> int:
    root, confirmed, _ = tools_dir()
    out = layout(root)
    out["confirmed"] = confirmed
    out["env"] = {"PLAYWRIGHT_BROWSERS_PATH": out["browsers_path"], "NODE_PATH": out["node_modules"]}
    print(json.dumps(out, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="screencraft tools setup (tools live outside projects)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="list installed and missing tools")
    c.add_argument("--tools-dir", help="check a different folder (does not save it)")
    c.add_argument("--python", help="base Python to use for the venv")
    c.set_defaults(fn=cmd_check)
    s = sub.add_parser("set-path", help="save the confirmed tools folder")
    s.add_argument("folder")
    s.set_defaults(fn=cmd_set_path)
    i = sub.add_parser("install", help="install missing tools (needs --yes)")
    i.add_argument("--yes", action="store_true", help="the user said yes")
    i.add_argument("--python", help="base Python to use for the venv")
    i.set_defaults(fn=cmd_install, tools_dir=None)
    p = sub.add_parser("paths", help="print tool locations as JSON")
    p.set_defaults(fn=cmd_paths)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
