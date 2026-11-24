#!/usr/bin/env python3
"""Scan the given files for values that should be tokens. Short output: file:line  kind  found -> fix.

Usage: python scan_code.py <files...> [--tokens PATH] [--limit N] [--json]

Finds, in the given files only:
  colour  hardcoded hex / rgb() / hsl() / oklch() (incl. Tailwind arbitrary bg-[#..]) -> nearest token
  size    px/rem values (arbitrary classes, inline styles, CSS) that match the spacing / radius scale
          (or sit off it: nearest value given)
  font    font sizes outside the type scale (text-[13px], fontSize: 13, font-size: 13px)
  style   inline styles (JSX style={{}}, Vue :style, HTML style="") with class suggestions
  html    raw HTML insertion (dangerouslySetInnerHTML, v-html, {@html}, innerHTML =, insertAdjacentHTML)
tokens.json is found automatically by walking up to .claude/screencraft/tokens.json, or pass --tokens.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from colorlib import composite, delta_e2000, parse_color  # noqa: E402
from match_tokens import load_groups  # noqa: E402

STYLE_EXT = {".css", ".scss", ".sass", ".less", ".pcss"}
HEX_RE = re.compile(r"(?<![&\w#])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})(?![\w-])")
FUNC_RE = re.compile(r"\b(?:rgba?|hsla?|oklch|oklab|hwb|lab|lch)\(\s*[^()$`{}]*?\)", re.I)
ARB_SIZE_RE = re.compile(r"(?<![\w-])(-?)((?:p|px|py|pt|pr|pb|pl|ps|pe|m|mx|my|mt|mr|mb|ml|ms|me|gap|gap-x|gap-y|"
                         r"space-x|space-y|w|h|min-w|min-h|max-w|max-h|size|top|right|bottom|left|inset|inset-x|inset-y|"
                         r"start|end|translate-x|translate-y|basis|indent|scroll-m|scroll-p)|rounded(?:-[trblse]{1,2})?|text)"
                         r"-\[(-?\d*\.?\d+)(px|rem)\]")
RAW_HTML_RE = re.compile(r"dangerouslySetInnerHTML|\bv-html\b|\{@html\b|\.(?:inner|outer)HTML\s*\+?=(?!=)|"
                         r"insertAdjacentHTML\s*\(|document\.write\s*\(")
JSX_STYLE_RE = re.compile(r"\bstyle=\{\{")
ATTR_STYLE_RE = re.compile(r"(?<![\w:-])(:?style)=\"([^\"]*)\"")
CSS_DECL_RE = re.compile(r"(?<![\w-])([a-z-]+)\s*:\s*([^;{}]+);")

SPACING_PROPS = {
    "padding": "p", "padding-top": "pt", "padding-right": "pr", "padding-bottom": "pb", "padding-left": "pl",
    "padding-inline": "px", "padding-block": "py", "padding-inline-start": "ps", "padding-inline-end": "pe",
    "margin": "m", "margin-top": "mt", "margin-right": "mr", "margin-bottom": "mb", "margin-left": "ml",
    "margin-inline": "mx", "margin-block": "my", "gap": "gap", "row-gap": "gap-y", "column-gap": "gap-x",
    "width": "w", "height": "h", "min-width": "min-w", "min-height": "min-h", "max-height": "max-h",
    "top": "top", "right": "right", "bottom": "bottom", "left": "left", "inset": "inset",
}
RADIUS_PROPS = {"border-radius": "rounded"}
FONT_PROPS = {"font-size": "text"}
COLOR_PROPS = {"color": "text", "background-color": "bg", "background": "bg", "border-color": "border",
               "border": "border", "fill": "fill", "stroke": "stroke", "outline-color": "outline",
               "box-shadow": "shadow", "text-decoration-color": "decoration", "caret-color": "caret"}


def kebab(k: str) -> str:
    return re.sub(r"([A-Z])", lambda m: "-" + m.group(1).lower(), k.strip().strip("'\""))


def find_tokens(start: Path):
    for d in [start] + list(start.parents):
        p = d / ".claude" / "screencraft" / "tokens.json"
        if p.exists():
            return p
    return None


class Ctx:
    def __init__(self, data):
        self.data = data
        self.groups = []
        self.scales = {}
        self.major = None
        if not data:
            return
        self.major = data["tailwind"].get("major")
        self.groups = load_groups(data, "light", False)
        # white/black are Tailwind built-ins, not a second palette
        for name in ("white", "black"):
            e = data["colors"]["tailwind"].get(name)
            if e and e.get("light"):
                hx = e["light"]["hex"]
                g = next((g for g in self.groups if g["hex"] == hx), None)
                if g is None:
                    self.groups.append({"hex": hx, "rgba": parse_color(hx), "names": [((0, 0), name, e)],
                                        "origin": "custom"})
                elif name not in [n for _, n, _ in g["names"]]:
                    g["names"].append(((0, 0), name, e))
        for cat in ("spacing", "radius", "fontSize"):
            vals = {}
            items = [(k, v) for k, v in (data["scales"].get(cat) or {}).items() if v.get("px") is not None]
            # Tailwind keys first (p-4, rounded-lg, text-sm); CSS variables (--space-4) fill the gaps
            for k, v in sorted(items, key=lambda kv: kv[0].startswith("--")):
                vals.setdefault(v["px"], k)
            self.scales[cat] = vals

    def colour(self, raw: str, prefix: str | None, css: bool):
        """Returns (status, fix_text, class_or_None) with status ok|near|ask, or None if not a colour."""
        c = parse_color(raw)
        if not c:
            return None
        if not self.groups:
            return "ask", "no tokens.json: run extract_tokens.py first", None
        probe = (*c[:3], 1.0)
        d, g = min(((delta_e2000(probe, g["rgba"]), g) for g in self.groups if g["rgba"]), key=lambda t: t[0])
        names = [n for _, n, _ in g["names"]]
        if css:
            pick = next((n for n in names if n.startswith("--")), None)
            scss = next((n for n in names if n.startswith("$")), None)
            main = f"var({pick})" if pick else (scss or f"theme(colors.{names[0]})")
            if c[3] < 1 and not pick and scss:
                main = f"rgba({scss}, {c[3]:g})"
            if c[3] < 1:
                interp = {n: str((e.get("light") or {}).get("interpreted_as", "")) for _, n, e in g["names"]}
                chan = next((n for n, i in interp.items() if n.startswith("--") and i.startswith("channels")), None)
                if chan:
                    fn = "hsl" if "hsl" in interp[chan] else "rgb"
                    main = f"{fn}(var({chan}) / {c[3]:g})"
                elif pick:
                    main = f"color-mix(in srgb, var({pick}) {round(c[3] * 100)}%, transparent)"
        else:
            tw = next((n for n in names if not n.startswith(("--", "$"))), None)
            var = next((n for n in names if n.startswith("--")), None)
            main = (f"{prefix}-{tw}" if (prefix and tw) else tw) or (f"var({var})" if var else
                                                                      f"{names[0]} (SCSS only: use it from a stylesheet)")
            if c[3] < 1 and tw:
                pct = round(c[3] * 100)
                main += f"/{pct}" if pct % 5 == 0 or (self.major or 0) >= 4 else f"/[{c[3]:.2f}]"
        alts = [n for n in names if n not in main][:3]
        alt = f" (same colour: {', '.join(alts)})" if alts else ""
        if d < 2:
            return "ok", f"{main}{alt}  dE {d:.1f}", main
        if d < 5:
            return "near", f"{main}{alt}  dE {d:.1f}, close: mention it", main
        return "ask", f"no token (nearest {main} dE {d:.0f}); match_tokens.py opacity test, else ask", None

    def size(self, cat: str, px: float, prefix: str):
        scale = self.scales.get(cat) or {}
        if not scale:
            return None, "no scale in tokens.json"
        neg = px < 0
        px = abs(px)

        def cls(key):
            if key.startswith("--"):
                return f"{'-' if neg else ''}var({key})" if not neg else f"calc(-1 * var({key}))"
            if cat == "spacing":
                return f"{'-' if neg else ''}{prefix}-{key}"
            if cat == "radius":
                return key.replace("rounded", prefix, 1) if prefix != "rounded" else key
            return key

        if px in scale:
            return True, f"{cls(scale[px])} ({px:g}px)"
        near = sorted(scale, key=lambda v: abs(v - px))[:2]
        near = sorted(near)
        return False, "off scale; nearest " + " or ".join(f"{cls(scale[v])} ({v:g}px)" for v in near)


def to_px(num: str, unit: str | None):
    n = float(num)
    return n * 16 if unit in ("rem", "em") else n


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def is_comment_line(text, pos):
    ls = text.rfind("\n", 0, pos) + 1
    head = text[ls:pos].lstrip()
    return head.startswith(("//", "*", "/*", "<!--", "{/*"))


def style_spans(text):
    """Return list of (start, end, body, kind) for inline style blocks."""
    spans = []
    for m in JSX_STYLE_RE.finditer(text):
        i, depth = m.end(), 2
        while i < len(text) and depth:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        spans.append((m.start(), i, text[m.end():i - 2], "jsx"))
    for m in ATTR_STYLE_RE.finditer(text):
        spans.append((m.start(), m.end(), m.group(2), "vue" if m.group(1) == ":style" else "attr"))
    return spans


def parse_style_pairs(body: str, kind: str):
    """Yield (kebab_prop, value_str, static: bool)."""
    if kind == "attr":
        for part in body.split(";"):
            if ":" in part:
                k, v = part.split(":", 1)
                yield kebab(k), v.strip(), "{" not in v
        return
    # JS object literal (jsx / vue :style="{...}"), top-level pairs only
    depth, cur, parts = 0, "", []
    for ch in body.strip().strip("{}"):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    for p in parts:
        p = p.strip()
        if not p or p.startswith("..."):
            if p:
                yield "...spread", p, False
            continue
        m = re.match(r"""^['"]?([\w-]+)['"]?\s*:\s*(.+)$""", p, re.S)
        if not m:
            continue
        v = m.group(2).strip()
        static = bool(re.fullmatch(r"""-?\d*\.?\d+|'[^'$]*'|"[^"$]*"|`[^`$]*`""", v))
        yield kebab(m.group(1)), v.strip("'\"`"), static


def shorthand(prefix: str, vals: list):
    """padding: 8px 16px -> py/px pairs."""
    if prefix not in ("p", "m") or len(vals) == 1:
        return [(prefix, v) for v in vals[:1]]
    if len(vals) == 2:
        return [(prefix + "y", vals[0]), (prefix + "x", vals[1])]
    if len(vals) == 3:
        return [(prefix + "t", vals[0]), (prefix + "x", vals[1]), (prefix + "b", vals[2])]
    return [(prefix + s, v) for s, v in zip("trbl", vals[:4])]


UTILITY = {
    ("display", "flex"): "flex", ("display", "grid"): "grid", ("display", "block"): "block",
    ("display", "inline-flex"): "inline-flex", ("display", "none"): "hidden", ("display", "inline-block"): "inline-block",
    ("align-items", "center"): "items-center", ("align-items", "flex-start"): "items-start",
    ("align-items", "flex-end"): "items-end", ("justify-content", "center"): "justify-center",
    ("justify-content", "space-between"): "justify-between", ("justify-content", "flex-end"): "justify-end",
    ("flex-direction", "column"): "flex-col", ("flex-wrap", "wrap"): "flex-wrap", ("flex", "1"): "flex-1",
    ("font-weight", "400"): "font-normal", ("font-weight", "500"): "font-medium", ("font-weight", "600"): "font-semibold",
    ("font-weight", "700"): "font-bold", ("font-weight", "bold"): "font-bold", ("cursor", "pointer"): "cursor-pointer",
    ("text-align", "center"): "text-center", ("text-align", "left"): "text-left", ("text-align", "right"): "text-right",
    ("position", "relative"): "relative", ("position", "absolute"): "absolute", ("position", "fixed"): "fixed",
    ("position", "sticky"): "sticky", ("overflow", "hidden"): "overflow-hidden", ("overflow", "auto"): "overflow-auto",
    ("white-space", "nowrap"): "whitespace-nowrap", ("width", "100%"): "w-full", ("height", "100%"): "h-full",
    ("border-radius", "50%"): "rounded-full", ("border-radius", "9999px"): "rounded-full",
    ("border-radius", "99px"): "rounded-full", ("border-radius", "999px"): "rounded-full",
    ("opacity", "0.5"): "opacity-50", ("text-transform", "uppercase"): "uppercase",
}


def value_findings(ctx: Ctx, prop: str, value: str, css: bool):
    """Suggestions for one declaration. Returns list of (kind, found, fix, status, classes)."""
    out = []
    util = UTILITY.get((prop, value.strip().strip("'\"").lower()))
    if util:
        return [("size" if prop == "border-radius" else "style", f"{prop}: {value.strip()}", util, "ok", util)]
    v = value.strip().rstrip(";")
    if not css and re.fullmatch(r"-?\d*\.?\d+", v) and prop in {**SPACING_PROPS, **RADIUS_PROPS, **FONT_PROPS}:
        v = v + "px"  # React treats bare numbers as px
    if prop in SPACING_PROPS or prop in RADIUS_PROPS or prop in FONT_PROPS:
        cat = "spacing" if prop in SPACING_PROPS else ("radius" if prop in RADIUS_PROPS else "fontSize")
        lens = re.findall(r"(-?\d*\.?\d+)(px|rem)\b", v)
        if css and lens and all(float(n) == 0 for n, _ in lens):
            lens = []
        if lens and not re.search(r"calc\(|var\(|clamp\(|%|vw|vh", v):
            prefix = SPACING_PROPS.get(prop) or RADIUS_PROPS.get(prop) or FONT_PROPS.get(prop)
            pairs = shorthand(prefix, lens) if cat == "spacing" else [(prefix, lens[0])]
            fixes, classes, on = [], [], True
            for pre, (n, u) in pairs:
                px = to_px(n, u)
                if px == 0:
                    fixes.append(f"{pre}-0")
                    classes.append(f"{pre}-0")
                    continue
                ok, fix = ctx.size(cat, px, pre)
                on = on and bool(ok)
                fixes.append(fix)
                if ok:
                    classes.append(fix.split(" ")[0])
            kind = "font" if cat == "fontSize" else "size"
            if css and on:
                fixes = [f + " (use the scale value)" for f in fixes[:1]] + fixes[1:]
            out.append((kind, f"{prop}: {value.strip()}", ", ".join(fixes), "ok" if on else "off",
                        " ".join(classes) if on else None))
    if prop in COLOR_PROPS or not css:
        for m in list(HEX_RE.finditer(v)) + list(FUNC_RE.finditer(v)):
            r = ctx.colour(m.group(0), COLOR_PROPS.get(prop), css)
            if r:
                out.append(("colour", f"{prop}: {m.group(0)}", r[1], r[0], r[2]))
    return out


def scan_file(path: Path, ctx: Ctx, sanitizer: str | None):
    text = path.read_text(encoding="utf-8", errors="replace")
    css = path.suffix.lower() in STYLE_EXT
    findings = []  # (line, kind, found, fix)
    spans = [] if css else style_spans(text)

    def in_span(pos):
        return any(s <= pos < e for s, e, _, _ in spans)

    # inline styles: one finding per block, with per-prop fixes folded in
    for s, e, body, kind in spans:
        line = line_of(text, s)
        if kind == "jsx" and is_comment_line(text, s):
            continue
        use, off, ask, other, static_props, dynamic_props = [], [], [], [], [], []
        for prop, val, static in parse_style_pairs(body, kind):
            (static_props if static else dynamic_props).append(prop)
            if not static:
                continue
            got = value_findings(ctx, prop, val, css=False)
            for k, found, fix, status, cls in got:
                if status in ("ok", "near") and cls:
                    use.append(cls + ("*" if status == "near" else ""))
                elif status == "off":
                    off.append(f"{found} ({fix.replace('off scale; nearest ', '')})")
                else:
                    short = re.sub(r"^no token \((.*?)\);.*$", r"\1", fix)
                    ask.append(f"{found.split(': ', 1)[-1]} ({short})")
            if not got:
                other.append(prop)
        if static_props:
            parts = []
            if use:
                parts.append("use: " + " ".join(dict.fromkeys(use)))
            if off:
                parts.append("off-scale: " + "; ".join(off))
            if ask:
                parts.append("no token: " + "; ".join(dict.fromkeys(ask)) + " -> match_tokens.py, else ask")
            if other:
                parts.append("also: " + ", ".join(other))
            findings.append((line, "style", f"style ({len(static_props)} static props)", " | ".join(parts)))
        elif dynamic_props:
            findings.append((line, "style", f"inline style, computed ({', '.join(dynamic_props)[:60]})",
                             "ok if the value is truly computed at runtime; static parts belong in classes"))

    # Tailwind arbitrary sizes / font sizes
    if not css:
        for m in ARB_SIZE_RE.finditer(text):
            if in_span(m.start()):
                continue
            neg, pre, num, unit = m.group(1), m.group(2), m.group(3), m.group(4)
            px = to_px(num, unit) * (-1 if neg else 1)
            cat = "fontSize" if pre == "text" else ("radius" if pre.startswith("rounded") else "spacing")
            ok, fix = ctx.size(cat, px, pre)
            kind = "font" if cat == "fontSize" else "size"
            if ok is True:
                findings.append((line_of(text, m.start()), kind, m.group(0), fix))
            else:
                findings.append((line_of(text, m.start()), kind, m.group(0), fix + ("" if ok is None else
                                 "; if the design truly needs this size, ask before adding a token")))

    # colours outside inline styles
    for m in list(HEX_RE.finditer(text)) + list(FUNC_RE.finditer(text)):
        pos = m.start()
        if in_span(pos) or is_comment_line(text, pos):
            continue
        ls = text.rfind("\n", 0, pos) + 1
        before = text[ls:pos]
        if re.search(r"(?:href|to|id|xlink:href)=\s*['\"{]?\s*$", before) or re.search(r"url\([^)]*$", before):
            continue
        decl_start = max(text.rfind(";", 0, pos), text.rfind("{", 0, pos), text.rfind("}", 0, pos), ls - 1)
        if re.match(r"\s*(--[\w-]+|\$[\w-]+)\s*:", text[decl_start + 1:pos]):  # token definition, not a use
            continue
        if css:
            pm = re.search(r"([a-z-]+)\s*:[^;:{}]*$", before)
            prop = pm.group(1) if pm else ""
            r = ctx.colour(m.group(0), COLOR_PROPS.get(prop), css=True)
            fix = r[1] if r else None
            found = f"{prop}: {m.group(0)}" if prop else m.group(0)
        else:
            am = re.search(r"(?<![\w-])([a-z]+(?:-[a-z]+)?)-\[$", before)
            prefix = am.group(1) if am else None
            pm = re.search(r"([a-zA-Z]+)\s*[:=]\s*['\"`]?$", before)
            if not prefix and pm:
                prefix = COLOR_PROPS.get(kebab(pm.group(1)))
            r = ctx.colour(m.group(0), prefix, css=False)
            fix = r[1] if r else None
            found = f"{prefix}-[{m.group(0)}]" if am else m.group(0)
        if fix:
            findings.append((line_of(text, pos), "colour", found, fix))

    # CSS declarations: sizes and font sizes
    if css:
        clean = re.sub(r"/\*.*?\*/", lambda x: re.sub(r"[^\n]", " ", x.group(0)), text, flags=re.S)
        for m in CSS_DECL_RE.finditer(clean):
            prop, val = m.group(1), m.group(2)
            if prop.startswith("--") or prop in COLOR_PROPS:
                continue
            for kind, found, fix, status, _ in value_findings(ctx, prop, val, css=True):
                if kind != "colour" and kind != "style":
                    findings.append((line_of(clean, m.start()), kind, found, fix))

    # raw HTML insertion
    for m in RAW_HTML_RE.finditer(text):
        if is_comment_line(text, m.start()):
            continue
        tip = (f"sanitize with {sanitizer} (installed) and confirm the source is trusted"
               if sanitizer else "confirm the HTML is trusted; no sanitizer is installed (adding one needs a yes)")
        findings.append((line_of(text, m.start()), "html", m.group(0).strip(),
                         f"render as text if possible; else {tip}"))
    return sorted(set(findings))


def main() -> int:
    ap = argparse.ArgumentParser(description="Scan files for hardcoded values that should be tokens")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--tokens")
    ap.add_argument("--limit", type=int, default=0, help="print at most N findings (0 = all)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    paths = [Path(f).resolve() for f in a.files]
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        print("not found: " + ", ".join(missing), file=sys.stderr)
        paths = [p for p in paths if p.is_file()]
    tpath = Path(a.tokens) if a.tokens else (find_tokens(paths[0].parent) if paths else None)
    data = json.loads(tpath.read_text(encoding="utf-8")) if tpath and tpath.exists() else None
    ctx = Ctx(data)
    sanitizer = None
    if tpath:
        project = tpath.resolve().parents[2]
        try:
            pkg = json.loads((project / "package.json").read_text(encoding="utf-8"))
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            sanitizer = next((s for s in ("isomorphic-dompurify", "dompurify", "sanitize-html", "xss") if s in deps), None)
        except (OSError, json.JSONDecodeError):
            pass
        base = project
    else:
        base = Path.cwd()
    all_f = []
    for p in paths:
        try:
            shown = Path(os.path.relpath(p, base)).as_posix()
        except ValueError:  # different drive on Windows
            shown = p.as_posix()
        all_f += [(shown, *f) for f in scan_file(p, ctx, sanitizer)]
    if a.json:
        print(json.dumps([dict(zip(("file", "line", "kind", "found", "fix"), f)) for f in all_f], indent=1))
        return 0
    if not data:
        print("note: tokens.json not found; colour and scale suggestions are limited. Run extract_tokens.py first.")
    counts = {}
    for f in all_f:
        counts[f[2]] = counts.get(f[2], 0) + 1
    print(f"{len(all_f)} findings in {len(paths)} file(s): " +
          (", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "clean"))
    shown_f = all_f[: a.limit] if a.limit else all_f
    for file, line, kind, found, fix in shown_f:
        print(f"{file}:{line}  {kind:<6} {found} -> {fix}")
    if a.limit and len(all_f) > a.limit:
        print(f"... {len(all_f) - a.limit} more (run without --limit for all)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
