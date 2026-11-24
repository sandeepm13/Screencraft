#!/usr/bin/env python3
"""Extract design tokens from a project into .claude/screencraft/tokens.json.

Usage: python extract_tokens.py <project> [--out PATH] [--no-node]

Reads (never writes) project files:
  - CSS / SCSS / Less files and <style> blocks in .vue/.svelte/.astro: CSS custom properties
    (light = :root/html/@theme, dark = .dark/[data-theme=dark]/prefers-color-scheme: dark,
    anything else = scoped) and SCSS $variables, with var() chains resolved.
  - Tailwind v3 config via the project's own tailwindcss/loadConfig + resolveConfig (Node).
  - Tailwind v4 @theme blocks + node_modules/tailwindcss/theme.css defaults.
Writes only the output JSON. Prints a short summary.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from colorlib import parse_channels, parse_color, to_hex  # noqa: E402

SKIP_DIRS = {"node_modules", ".git", ".next", ".nuxt", ".output", ".svelte-kit", "dist", "build", "out",
             "coverage", ".turbo", ".vercel", ".cache", ".claude", "vendor", "storybook-static", "__pycache__",
             ".venv", "venv"}
STYLE_EXT = {".css", ".scss", ".sass", ".less", ".pcss"}
SFC_EXT = {".vue", ".svelte", ".astro"}
SOURCE_EXT = {".tsx", ".jsx", ".ts", ".js", ".mjs", ".cjs", ".vue", ".svelte", ".astro", ".html", ".mdx"} | STYLE_EXT

DARK_RE = re.compile(r"\.dark\b|\[data-(?:theme|mode|color-scheme|bs-theme)=['\"]?dark|prefers-color-scheme:\s*dark"
                     r"|\.theme-dark\b|\.dark-theme\b|\.dark-mode\b", re.I)
GLOBAL_PART_RE = re.compile(r"^(?::root|html|body|:host|\*|\.light|\.theme-light|\[data-(?:theme|mode)=['\"]?light['\"]?\]"
                            r"|@theme(?:\s+[\w-]+)*|@layer(?:\s+[\w,\s-]+)?|@media\s*\(prefers-color-scheme:\s*light\)"
                            r"|html:root|:root:root)$", re.I)
VAR_RE = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,((?:[^()]|\([^()]*\))*))?\)")
SCSS_REF_RE = re.compile(r"\$([\w-]+)")
LEN_RE = re.compile(r"^(-?\d*\.?\d+)(px|rem|em)?$")

TW_COLOR_PREFIX = (r"(?:bg|text|border(?:-[xytrblse])?|ring(?:-offset)?|outline|fill|stroke|from|via|to|divide"
                   r"|placeholder|caret|accent|decoration|shadow)")
SHADE_CLASS_RE = re.compile(r"(?<![\w/\-\[])" + TW_COLOR_PREFIX + r"-([a-z][a-z0-9]*(?:-[a-z][a-z0-9]*)*-(?:50|[1-9]00|950))"
                            r"(?:/\d+)?(?![\w-])")
UTILITY_OVERRIDE_RE = re.compile(r"^\.(?:-?[mp][trblxyse]?-[\d.]+|(?:w|h|gap|inset|top|left|right|bottom)-[\d.]+"
                                 r"|text-(?:xs|sm|base|lg|[2-9]?xl)|rounded(?:-\w+)?|shadow(?:-\w+)?|container"
                                 r"|hidden|block|flex|grid)$")


# ---------------------------------------------------------------- file walking

def walk(root: Path):
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in fns:
            p = Path(dp) / fn
            if p.suffix.lower() in SOURCE_EXT and not fn.endswith((".min.css", ".min.js", ".map", ".d.ts")):
                yield p


def rel(root: Path, p: Path) -> str:
    try:
        return p.relative_to(root).as_posix()
    except ValueError:
        return p.as_posix()


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# ---------------------------------------------------------------- CSS parsing

def _blank(m):
    return re.sub(r"[^\n]", " ", m.group(0))


def strip_comments(text: str, line_comments: bool) -> str:
    text = re.sub(r"/\*.*?\*/", _blank, text, flags=re.S)
    if line_comments:
        text = re.sub(r"(?<![:\"'\\/])//[^\n]*", _blank, text)
    return text


def parse_css(text: str, base_line: int = 1):
    """Yield (name, value, ctx_tuple, line, kind) for --custom-props and $scss vars, plus ('rule', selector, line)."""
    decls, rules = [], []
    stack: list[str] = []
    buf, buf_line, line = [], None, base_line
    in_str, paren = None, 0

    def flush():
        s = "".join(buf)
        m = re.match(r"\s*(--[\w-]+|\$[\w-]+)\s*:\s*(.*)$", s, re.S)
        if m:
            val = re.sub(r"\s*!(?:important|default|global)\s*$", "", m.group(2).strip())
            decls.append((m.group(1), " ".join(val.split()), tuple(stack), buf_line))

    for ch in text:
        if in_str:
            buf.append(ch)
            if ch == in_str:
                in_str = None
        elif ch in "\"'":
            in_str = ch
            buf.append(ch)
        elif ch == "(":
            paren += 1
            buf.append(ch)
        elif ch == ")":
            paren = max(0, paren - 1)
            buf.append(ch)
        elif paren == 0 and ch == "{":
            prelude = " ".join("".join(buf).split())
            stack.append(prelude)
            rules.append((prelude, buf_line, len(stack)))
            buf, buf_line = [], None
        elif paren == 0 and ch == "}":
            flush()
            if stack:
                stack.pop()
            buf, buf_line = [], None
        elif paren == 0 and ch == ";":
            flush()
            buf, buf_line = [], None
        else:
            if buf_line is None and not ch.isspace():
                buf_line = line
            buf.append(ch)
        if ch == "\n":
            line += 1
    flush()
    return decls, rules


def classify(ctx: tuple) -> str:
    joined = " ".join(ctx)
    if DARK_RE.search(joined):
        return "dark"
    for item in ctx:
        parts = [p.strip() for p in item.split(",")] if not item.startswith("@") else [item]
        if not all(GLOBAL_PART_RE.match(p) for p in parts):
            return "scoped"
    return "light"


# ---------------------------------------------------------------- Tailwind v3 via node

NODE_JS = r"""
const proj = process.env.SC_PROJECT, cfg = process.env.SC_CFG;
const r = (m) => require(require.resolve(m, { paths: [proj] }));
let raw;
try { raw = r('tailwindcss/loadConfig')(cfg); } catch (e) { raw = require(cfg); }
if (raw && raw.default) raw = raw.default;
const full = r('tailwindcss/resolveConfig')(raw);
const t = full.theme;
const rep = (k, v) => (typeof v === 'function' ? '[function]' : v);
process.stdout.write(JSON.stringify({
  raw: { theme: raw.theme || {}, darkMode: raw.darkMode === undefined ? null : raw.darkMode, prefix: raw.prefix || '' },
  resolved: { colors: t.colors, spacing: t.spacing, fontSize: t.fontSize, borderRadius: t.borderRadius,
              boxShadow: t.boxShadow, screens: t.screens, zIndex: t.zIndex, fontFamily: t.fontFamily },
}, rep));
"""


def load_tw3(root: Path, cfg: Path):
    env = dict(os.environ, SC_PROJECT=str(root), SC_CFG=str(cfg), JITI_CACHE="false")
    try:
        out = subprocess.run(["node", "-e", NODE_JS], cwd=str(root), env=env, capture_output=True,
                             text=True, timeout=60, encoding="utf-8")
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"node failed: {e}"
    if out.returncode != 0:
        return None, "node failed: " + (out.stderr.strip().splitlines() or ["?"])[-1][:200]
    try:
        return json.loads(out.stdout), None
    except json.JSONDecodeError:
        return None, "node output was not JSON"


def flatten(obj, prefix=""):
    out = {}
    if not isinstance(obj, dict):
        return out
    for k, v in obj.items():
        name = prefix if k == "DEFAULT" else (f"{prefix}-{k}" if prefix else str(k))
        if isinstance(v, dict):
            out.update(flatten(v, name))
        else:
            out[name] = v
    return out


def config_line(lines: list[str], path_keys: list[str]) -> int | None:
    """Find the line of a nested key like ['forest','50'] in a JS config (best effort)."""
    start = 0
    found = None
    for key in path_keys:
        pat = re.compile(r"^\s*['\"]?" + re.escape(key) + r"['\"]?\s*:")
        for i in range(start, len(lines)):
            if pat.search(lines[i]):
                found, start = i + 1, i + 1
                break
        else:
            return found
    return found


# ---------------------------------------------------------------- helpers

def to_px(v):
    if isinstance(v, (int, float)):
        return float(v)
    if not isinstance(v, str):
        return None
    m = LEN_RE.match(v.strip())
    if not m:
        return None
    n = float(m.group(1))
    return n * 16 if m.group(2) in ("rem", "em") else n


def name_category(name: str, value: str) -> str | None:
    n = name.lstrip("-$").lower()
    if re.match(r"(spacing|space|gap|gutter|pad|padding|margin)\b|spacing$", n):
        return "spacing"
    if re.match(r"(radius|rounded|border-radius)", n):
        return "radius"
    if re.match(r"(shadow|elevation|box-shadow)", n):
        return "shadow"
    if re.match(r"(z|z-index|layer|zindex)(-|$)", n):
        return "zIndex"
    if re.match(r"(breakpoint|bp|screen)(-|$)", n):
        return "screens"
    if re.match(r"(font-size|fs|text|type|font)(-|$)", n) and re.search(r"\d(px|rem|em)|clamp\(", value):
        return "fontSize"
    if re.match(r"font(-family)?(-|$)", n) and re.search(r"sans|serif|mono|['\",]", value):
        return "fontFamily"
    return None


# ---------------------------------------------------------------- main extraction

def extract(root: Path, use_node: bool = True):
    notes, warnings, unresolved = [], [], []
    files = list(walk(root))

    # -- package.json / tailwind detection
    pkg = {}
    try:
        pkg = json.loads(read(root / "package.json") or "{}")
    except json.JSONDecodeError:
        notes.append("package.json is not valid JSON")
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    tw_ver = deps.get("tailwindcss")
    installed = root / "node_modules" / "tailwindcss" / "package.json"
    if installed.exists():
        try:
            tw_ver = json.loads(read(installed)).get("version", tw_ver)
        except json.JSONDecodeError:
            pass
    tw_major = None
    if tw_ver:
        m = re.search(r"(\d+)", tw_ver)
        tw_major = int(m.group(1)) if m else None

    # -- parse style files
    vars_: dict[str, dict[str, list]] = defaultdict(lambda: {"light": [], "dark": [], "scoped": []})
    theme_vars: set[str] = set()  # declared inside @theme (tailwind v4)
    has_theme_block = False
    for p in files:
        ext = p.suffix.lower()
        if ext in STYLE_EXT:
            chunks = [(read(p), 1)]
        elif ext in SFC_EXT:
            text = read(p)
            chunks = [(m.group(1), text[: m.start(1)].count("\n") + 1)
                      for m in re.finditer(r"<style[^>]*>(.*?)</style>", text, re.S)]
        else:
            continue
        for text, base in chunks:
            if not text:
                continue
            text = strip_comments(text, line_comments=ext in {".scss", ".sass", ".less", ".vue", ".svelte", ".astro"})
            decls, rules = parse_css(text, base)
            for name, value, ctx, line in decls:
                where = f"{rel(root, p)}:{line}"
                if name.startswith("$"):
                    if not ctx:
                        vars_[name]["light"].append((value, where, ""))
                    continue
                bucket = classify(ctx)
                vars_[name][bucket].append((value, where, " > ".join(ctx)))
                if any(c.startswith("@theme") for c in ctx):
                    theme_vars.add(name)
                    has_theme_block = True
            if tw_major is not None or has_theme_block:
                for sel, line, depth in rules:
                    if depth == 1 and UTILITY_OVERRIDE_RE.match(sel):
                        warnings.append(f"{rel(root, p)}:{line} redefines Tailwind utility '{sel}' globally "
                                        f"(the class no longer means the Tailwind value)")
    if tw_major is None and has_theme_block:
        tw_major = 4

    def last(name, theme):
        d = vars_.get(name)
        if not d:
            return None
        if theme == "dark" and d["dark"]:
            return d["dark"][-1]
        return d["light"][-1] if d["light"] else None

    def resolve(value: str, theme: str):
        chain, dark_hit = [], [False]

        def sub_var(m):
            nm, fb = m.group(1), m.group(2)
            hit = last(nm, theme)
            if hit is None:
                return fb.strip() if fb is not None else m.group(0).replace("var(", "unresolved(")
            chain.append(nm)
            if theme == "dark" and vars_[nm]["dark"]:
                dark_hit[0] = True
            return hit[0]

        def sub_scss(m):
            nm = "$" + m.group(1)
            hit = last(nm, "light")
            if hit is None:
                return m.group(0)
            chain.append(nm)
            return hit[0]

        v = value
        for _ in range(25):
            nv = VAR_RE.sub(sub_var, v)
            nv = SCSS_REF_RE.sub(sub_scss, nv)
            if nv == v:
                break
            v = nv
        v = v.replace("<alpha-value>", "1")
        return v, chain, dark_hit[0]

    def as_color(resolved: str, fn_hint=None):
        c = parse_color(resolved)
        if c:
            return c, None
        pc = parse_channels(resolved, fn_hint)
        if pc:
            return pc[0], f"channels ({pc[1]})"
        return None, None

    colors: dict[str, dict] = {}
    scales: dict[str, dict] = defaultdict(dict)

    def mk(c, raw, chain, interp, where=None):
        item = {"hex": to_hex(c), "raw": raw}
        if chain:
            item["chain"] = chain
        if interp:
            item["interpreted_as"] = interp
        if where:
            item["defined_at"] = where
        return item

    def color_entry(name, kind, raw_value, where, origin, fn_hint=None):
        entry = {"kind": kind, "origin": origin}
        res, chain, _ = resolve(raw_value, "light")
        c, interp = as_color(res, fn_hint)
        if not c:
            return None, res
        entry["light"] = mk(c, raw_value, chain, interp)
        own_dark = kind == "css-var" and bool(vars_[name]["dark"])
        dark_raw = vars_[name]["dark"][-1][0] if own_dark else raw_value
        res_d, chain_d, hit = resolve(dark_raw, "dark")
        if own_dark or hit:
            cd, interp_d = as_color(res_d, fn_hint)
            entry["dark"] = (mk(cd, dark_raw, chain_d, interp_d, vars_[name]["dark"][-1][1] if own_dark else None)
                             if cd else {"unresolved": res_d})
        else:
            entry["dark"] = None
        if where:
            entry["defined_at"] = where
        return entry, None

    # -- CSS vars and SCSS vars
    for name, d in vars_.items():
        if d["light"]:
            value, where, ctx = d["light"][-1]
        elif d["dark"]:
            value, where, ctx = d["dark"][-1]
        else:
            # only scoped definitions: record as scoped colours / scale values, not as global tokens
            value, where, ctx = d["scoped"][-1]
            res, _, _ = resolve(value, "light")
            c, _ = as_color(res)
            if c:
                colors.setdefault("scoped", {})[name] = {"hex": to_hex(c), "raw": value, "defined_at": where,
                                                        "selector": ctx}
            continue
        kind = "scss-var" if name.startswith("$") else "css-var"
        res, _, _ = resolve(value, "light")
        entry, bad = color_entry(name, kind, value, where, "custom")
        if entry:
            if len(d["light"]) > 1:
                entry["also_defined_at"] = [w for _, w, _ in d["light"][:-1]][:5]
            if d["scoped"]:
                entry["scoped_overrides"] = [f"{w} ({c})" for _, w, c in d["scoped"]][:5]
            if name in theme_vars:
                entry["tailwind_theme_var"] = True
            colors.setdefault("vars", {})[name] = entry
            continue
        cat = name_category(name, res)
        if name in theme_vars:
            for ns, c2 in (("--spacing", "spacing"), ("--radius", "radius"), ("--shadow", "shadow"),
                           ("--breakpoint", "screens"), ("--text", "fontSize"), ("--font-weight", None),
                           ("--font", "fontFamily"), ("--leading", None), ("--tracking", None)):
                if name == ns or name.startswith(ns + "-"):
                    cat = c2
                    break
            if name.startswith("--text-") and "--" in name[7:]:
                cat = None  # --text-sm--line-height
        if cat:
            scales[cat][name] = {"value": res, "px": to_px(res), "origin": "custom", "defined_at": where}
        elif re.search(r"unresolved\(|color-mix\(|\b(?:darken|lighten|mix|rgba?\(\$)", res) and \
                re.search(r"color|bg|background|border|text|fg|primary|secondary|accent", name, re.I):
            unresolved.append(f"{name} = {value} ({where})")

    # -- Tailwind v3 config
    tw_tokens: dict[str, dict] = {}
    tw_prefix = ""
    tw_dark_mode = None
    cfg_path = next((root / f for f in ("tailwind.config.ts", "tailwind.config.js", "tailwind.config.cjs",
                                        "tailwind.config.mjs", "tailwind.config.mts", "tailwind.config.cts")
                     if (root / f).exists()), None)
    if cfg_path and (tw_major or 3) < 4:
        data, err = (load_tw3(root, cfg_path) if use_node else (None, "--no-node given"))
        if err:
            notes.append(f"Tailwind config not evaluated ({err}); Tailwind colour tokens missing — read {cfg_path.name} by hand")
        else:
            raw_theme = data["raw"]["theme"] or {}
            tw_prefix = data["raw"].get("prefix") or ""
            tw_dark_mode = data["raw"].get("darkMode")
            cfg_lines = read(cfg_path).splitlines()
            cfg_rel = rel(root, cfg_path)
            ext = raw_theme.get("extend", {}) or {}
            raw_colors = {**flatten(raw_theme.get("colors", {}) if isinstance(raw_theme.get("colors"), dict) else {}),
                          **flatten(ext.get("colors", {}) if isinstance(ext.get("colors"), dict) else {})}
            for name, value in flatten(data["resolved"]["colors"]).items():
                if name in ("inherit", "current", "transparent") or not isinstance(value, str):
                    continue
                origin = "custom" if name in raw_colors else "default"
                keys = name.split("-")
                line = config_line(cfg_lines, ["colors"] + keys) if origin == "custom" else None
                if origin == "custom" and line is None:
                    line = config_line(cfg_lines, ["colors", keys[0]])
                fn_hint = "hsl" if value.startswith("hsl(") else ("rgb" if value.startswith("rgb(") else None)
                entry, bad = color_entry(name, "tailwind", value, f"{cfg_rel}:{line}" if line else
                                         (cfg_rel if origin == "custom" else ""), origin, fn_hint)
                if entry:
                    tw_tokens[name] = entry
                elif origin == "custom":
                    unresolved.append(f"tailwind {name} = {value} -> {bad}")
            # scales
            for key, cat in (("spacing", "spacing"), ("fontSize", "fontSize"), ("borderRadius", "radius"),
                             ("boxShadow", "shadow"), ("screens", "screens"), ("zIndex", "zIndex"),
                             ("fontFamily", "fontFamily")):
                custom_keys = set()
                for src in (raw_theme.get(key), ext.get(key)):
                    if isinstance(src, dict):
                        custom_keys |= set(src)
                for k, v in (data["resolved"].get(key) or {}).items():
                    size = v[0] if isinstance(v, list) and v and isinstance(v[0], str) and key == "fontSize" else v
                    lh = None
                    if key == "fontSize" and isinstance(v, list) and len(v) > 1:
                        lh = v[1].get("lineHeight") if isinstance(v[1], dict) else v[1]
                    if key == "fontFamily" and isinstance(v, list):
                        size = ", ".join(map(str, v))
                    item = {"value": size, "px": to_px(size) if key not in ("zIndex", "fontFamily", "boxShadow") else None,
                            "origin": "custom" if k in custom_keys else "default"}
                    if key == "zIndex":
                        item["px"] = None
                    if lh:
                        item["lineHeight"] = lh
                    if k in custom_keys:
                        ln = config_line(cfg_lines, [key, k])
                        if ln:
                            item["defined_at"] = f"{cfg_rel}:{ln}"
                    cls = {"spacing": "", "fontSize": "text-", "radius": "rounded-", "shadow": "shadow-",
                           "screens": "", "zIndex": "z-", "fontFamily": "font-"}[cat]
                    tw_name = (cls + k) if cat not in ("radius", "shadow") or k != "DEFAULT" else cls.rstrip("-")
                    scales[cat][tw_name if cat != "spacing" else k] = item

    # -- Tailwind v4: @theme vars + defaults from node_modules/tailwindcss/theme.css
    defaults_missing = False
    if tw_major and tw_major >= 4:
        defaults_css = root / "node_modules" / "tailwindcss" / "theme.css"
        default_vars = {}
        if defaults_css.exists():
            decls, _ = parse_css(strip_comments(read(defaults_css), False))
            default_vars = {n: v for n, v, _, _ in decls}
        else:
            notes.append("Tailwind v4 default theme.css not found in node_modules (dependencies not installed?); "
                         "default palette and scales skipped, unknown-class check off")
            defaults_missing = True
        for name in sorted(theme_vars):
            if name.startswith("--color-"):
                e = colors.get("vars", {}).get(name)
                if e:
                    tw_tokens[name[len("--color-"):]] = {**e, "kind": "tailwind", "via": name}
        reset_colors = any(n == "--color-*" for n in vars_)
        for name, value in default_vars.items():
            if name.startswith("--color-") and not reset_colors:
                tname = name[len("--color-"):]
                if tname not in tw_tokens:
                    c = parse_color(value)
                    if c:
                        tw_tokens[tname] = {"kind": "tailwind", "origin": "default",
                                            "light": {"hex": to_hex(c), "raw": value}, "dark": None}
            for ns, cat, cls in (("--radius-", "radius", "rounded-"), ("--shadow-", "shadow", "shadow-"),
                                 ("--breakpoint-", "screens", ""), ("--font-", "fontFamily", "font-")):
                if name.startswith(ns) and not name.startswith("--font-weight"):
                    k = cls + name[len(ns):]
                    scales[cat].setdefault(k, {"value": value, "px": to_px(value) if cat in ("radius", "screens") else None,
                                               "origin": "default"})
            if name.startswith("--text-") and "--" not in name[7:]:
                k = "text-" + name[7:]
                scales["fontSize"].setdefault(k, {"value": value, "px": to_px(value), "origin": "default",
                                                  "lineHeight": default_vars.get(name + "--line-height")})
        base = scales["spacing"].get("--spacing", {}).get("value") or default_vars.get("--spacing")
        if base and to_px(base):
            unit = to_px(base)
            for n in [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 16, 20, 24, 28, 32, 36, 40, 44,
                      48, 52, 56, 60, 64, 72, 80, 96]:
                k = (str(n).rstrip("0").rstrip(".") if isinstance(n, float) else str(n))
                scales["spacing"].setdefault(k, {"value": f"calc(var(--spacing) * {k})", "px": n * unit,
                                                 "origin": "default"})
            scales["spacing"].setdefault("px", {"value": "1px", "px": 1.0, "origin": "default"})
        # rename v4 custom @theme scale keys to class names
        for cat, ns, cls in (("radius", "--radius-", "rounded-"), ("shadow", "--shadow-", "shadow-"),
                             ("fontSize", "--text-", "text-"), ("screens", "--breakpoint-", ""),
                             ("fontFamily", "--font-", "font-")):
            for k in [k for k in scales[cat] if k.startswith(ns) and k in theme_vars]:
                scales[cat][cls + k[len(ns):]] = scales[cat].pop(k)

    # -- class + var usage scan
    tw_names = sorted(tw_tokens, key=len, reverse=True)
    class_re = None
    if tw_names:
        alt = "|".join(re.escape(n) for n in tw_names)
        class_re = re.compile(r"(?<![\w/\-\[])(" + re.escape(tw_prefix) + TW_COLOR_PREFIX + r")-(" + alt +
                              r")(/(?:\d+|\[[^\]\s]+\]))?(?![\w-])")
    class_counts: dict[str, Counter] = defaultdict(Counter)
    var_counts: Counter = Counter()
    unknown_shade: dict[str, list] = defaultdict(list)
    dark_variant_uses = 0
    var_use_re = re.compile(r"var\(\s*(--[\w-]+)")
    known = set(tw_tokens)
    for p in files:
        text = read(p)
        if not text:
            continue
        is_style = p.suffix.lower() in STYLE_EXT
        for m in var_use_re.finditer(text):
            ls = text.rfind("\n", 0, m.start()) + 1
            if not re.match(r"\s*--[\w-]+\s*:", text[ls:m.start()]):  # skip token-definition lines
                var_counts[m.group(1)] += 1
        if class_re and not is_style:
            for m in class_re.finditer(text):
                class_counts[m.group(2)][m.group(1) + "-" + m.group(2) + (m.group(3) or "")] += 1
            dark_variant_uses += len(re.findall(r"(?<![\w-])dark:", text))
            if tw_names and not defaults_missing:
                for m in SHADE_CLASS_RE.finditer(text):
                    if m.group(1) not in known and not m.group(1).startswith("opacity-") \
                            and len(unknown_shade[m.group(0)]) < 3:
                        unknown_shade[m.group(0)].append(f"{rel(root, p)}:{text[: m.start()].count(chr(10)) + 1}")

    for name, e in tw_tokens.items():
        e["classes"] = dict(class_counts[name].most_common())
    # keep default palette entries only if the project actually uses them
    tw_tokens = {n: e for n, e in tw_tokens.items() if e["origin"] == "custom" or e["classes"]}
    for name, e in colors.get("vars", {}).items():
        e["var_uses"] = var_counts.get(name, 0)

    for cls, where in sorted(unknown_shade.items()):
        warnings.append(f"unknown colour class '{cls}' (no such token; compiles to nothing) at {', '.join(where)}")

    has_dark = any(d["dark"] for d in vars_.values()) or dark_variant_uses > 0 or bool(tw_dark_mode)
    for p in files:
        if p.suffix.lower() in {".ts", ".tsx", ".js", ".jsx"}:
            t = read(p)
            m = re.search(r"\b(createTheme|extendTheme|createStitches|defineConfig\(\{\s*theme|MantineProvider|"
                          r"ConfigProvider[^>]*theme=)", t)
            if m and not p.name.startswith("tailwind.config"):
                notes.append(f"JS theme object ({m.group(1)}) in {rel(root, p)}:{t[: m.start()].count(chr(10)) + 1} "
                             f"is not parsed; read it by hand")

    return {
        "project": root.name,
        "tailwind": {"version": tw_ver, "major": tw_major, "config": rel(root, cfg_path) if cfg_path else None,
                     "prefix": tw_prefix, "darkMode": tw_dark_mode},
        "themes": {"has_dark": has_dark, "dark_css_vars": sum(1 for d in vars_.values() if d["dark"]),
                   "dark_variant_uses": dark_variant_uses},
        "colors": {"tailwind": tw_tokens, "vars": colors.get("vars", {}), "scoped": colors.get("scoped", {})},
        "scales": {k: v for k, v in scales.items() if v},
        "unresolved": unresolved,
        "warnings": warnings,
        "notes": notes,
    }


def summary(data: dict, out: Path) -> str:
    tw = data["colors"]["tailwind"]
    v = data["colors"]["vars"]
    custom = sum(1 for e in tw.values() if e["origin"] == "custom")
    defaults_used = [n for n, e in tw.items() if e["origin"] == "default"]
    with_dark = sum(1 for e in list(tw.values()) + list(v.values()) if e.get("dark"))
    lines = [f"tokens.json -> {out}",
             f"Tailwind: {data['tailwind']['version'] or 'not installed'} (config: {data['tailwind']['config'] or 'none'})",
             f"Colours: {custom} Tailwind custom, {len(defaults_used)} Tailwind default palette in use, "
             f"{len(v)} CSS/SCSS vars, {len(data['colors']['scoped'])} scoped-only",
             f"Dark theme: {'yes' if data['themes']['has_dark'] else 'no'} "
             f"({data['themes']['dark_css_vars']} dark vars, {data['themes']['dark_variant_uses']} dark: classes, "
             f"{with_dark} tokens with a dark value)"]
    if defaults_used:
        top = sorted(defaults_used, key=lambda n: -sum(tw[n]["classes"].values()))[:8]
        lines.append("Default-palette colours used: " + ", ".join(
            f"{n}({sum(tw[n]['classes'].values())})" for n in top) + (" ..." if len(defaults_used) > 8 else ""))
    for cat, vals in data["scales"].items():
        c = sum(1 for x in vals.values() if x.get("origin") == "custom")
        lines.append(f"Scale {cat}: {len(vals)} values ({c} custom)")
    unused = [n for n, e in tw.items() if e["origin"] == "custom" and not e["classes"]]
    if unused:
        lines.append(f"Custom Tailwind colours with no class use: {', '.join(unused[:12])}" + (" ..." if len(unused) > 12 else ""))
    for k in ("unresolved", "warnings", "notes"):
        for item in data[k][:10]:
            lines.append(f"{k[:-1] if k != 'notes' else 'note'}: {item}")
        if len(data[k]) > 10:
            lines.append(f"... {len(data[k]) - 10} more {k} in tokens.json")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Extract design tokens into .claude/screencraft/tokens.json")
    ap.add_argument("project")
    ap.add_argument("--out", help="output path (default <project>/.claude/screencraft/tokens.json)")
    ap.add_argument("--no-node", action="store_true", help="do not evaluate tailwind.config with node")
    a = ap.parse_args()
    root = Path(a.project).resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2
    data = extract(root, use_node=not a.no_node)
    out = Path(a.out) if a.out else root / ".claude" / "screencraft" / "tokens.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    print(summary(data, out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
