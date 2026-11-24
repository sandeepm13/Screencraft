#!/usr/bin/env python3
"""Match colours (e.g. sampled from a screenshot) to the project's tokens by Delta E 2000.

Usage:
  python match_tokens.py --tokens <project>/.claude/screencraft/tokens.json --colors "#0a5f38,#e7efeb"
                         [--background "#ffffff"] [--theme light|dark] [--include-defaults] [--json]

Rules (from references/tokens-and-reuse.md):
  dE < 2   -> USE the token (certain)
  2 to 5   -> USE the token and MENTION it to the user
  > 5      -> test token at opacity over the background (e.g. primary/10)
  no match -> ASK the user. Never invent a token, never start a second palette.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from colorlib import composite, contrast, delta_e2000, parse_color, split_colors, to_hex  # noqa: E402

CERTAIN, CLOSE = 2.0, 5.0
STEPS = [x / 100 for x in range(5, 100, 5)]
FINE = [x / 100 for x in range(1, 100)]


def load_groups(data: dict, theme: str, include_defaults: bool):
    """Group tokens by resolved hex. Returns list of dicts: hex, rgba, names(list), dark(dict name->hex)."""
    groups: dict[str, dict] = {}

    def add(name, entry, rank):
        item = entry.get(theme) or entry.get("light")
        if not item or "hex" not in item:
            return
        hx = item["hex"].lower()
        g = groups.setdefault(hx, {"hex": hx, "rgba": parse_color(hx), "names": [], "origin": entry["origin"]})
        g["names"].append((rank, name, entry))
        if entry["origin"] == "custom":
            g["origin"] = "custom"

    for name, e in data["colors"]["tailwind"].items():
        if e["origin"] == "custom" or include_defaults:
            uses = sum(e.get("classes", {}).values())
            add(name, e, (0 if e["origin"] == "custom" else 2, -uses))
    for name, e in data["colors"]["vars"].items():
        # semantic aliases (value is var(...)) before raw palette literals, then by real use count
        literal = 0 if "var(" in str((e.get("light") or {}).get("raw", "")) else 1
        add(name, e, (1, literal, -e.get("var_uses", 0)))
    out = []
    for g in groups.values():
        g["names"].sort(key=lambda t: t[0])
        out.append(g)
    return out


def defaults_groups(data: dict, theme: str):
    return [g for g in load_groups(data, theme, True) if g["origin"] == "default"]


def label(g, maxn=4):
    names = [n for _, n, _ in g["names"]]
    head = names[0]
    rest = names[1:maxn]
    s = head
    if rest:
        s += " (= " + ", ".join(rest) + (" ..." if len(names) > maxn else "") + ")"
    return s


def find_background(data, theme, arg):
    if arg:
        c = parse_color(arg)
        if not c:
            sys.exit(f"cannot parse --background {arg!r}")
        return c, arg
    for src, key in ((data["colors"]["tailwind"], "background"), (data["colors"]["vars"], "--background")):
        e = src.get(key)
        if e:
            item = e.get(theme) or e.get("light")
            if item and "hex" in item:
                return parse_color(item["hex"]), f"{key} {item['hex']}"
    return parse_color("#ffffff"), "white (no background token found)"


def opacity_match(target, groups, bg, bg_hex, alphas):
    best = None
    for g in groups:
        if g["hex"][:7] == bg_hex[:7] or g["rgba"] is None:
            continue
        for a in alphas:
            mixed = composite((*g["rgba"][:3], a), bg)
            d = delta_e2000(target, mixed)
            if best is None or d < best[0]:
                best = (d, g, a)
    return best


def tw_alpha(a: float, major) -> str:
    pct = round(a * 100)
    if pct % 5 == 0 or (major and major >= 4):
        return f"/{pct}"
    return f"/[{a:.2f}]"


def with_alpha(g, a: float, major) -> str:
    """'primary/10' for a Tailwind colour; 'var(--x) at 10%' when only a CSS variable exists."""
    tw = next((n for _, n, _ in g["names"] if not n.startswith(("--", "$"))), None)
    if tw:
        return f"{tw}{tw_alpha(a, major)}"
    first = g["names"][0][1]
    return f"rgba({first}, {a:g})" if first.startswith("$") else f"var({first}) at {round(a * 100)}%"


def match_one(raw, groups, data, theme, bg, bg_label, show_contrast):
    c = parse_color(raw)
    if not c:
        return {"input": raw, "verdict": "ERROR", "text": f"{raw} -> cannot parse"}
    major = data["tailwind"].get("major")
    bg_hex = to_hex(bg)
    res = {"input": raw}
    # Translucent input (rgba / #rrggbbaa): match its opaque part and keep its alpha.
    target = composite(c, bg) if c[3] < 1 else c
    probe = (*c[:3], 1.0)
    ranked = sorted(((delta_e2000(probe, g["rgba"]), g) for g in groups if g["rgba"]), key=lambda t: t[0])
    if not ranked:
        return {"input": raw, "verdict": "ASK", "text": f"{raw} -> ASK: tokens.json has no colour tokens"}
    d, g = ranked[0]
    nearest = ", ".join(f"{label(x, 2)} {dd:.1f}" for dd, x in ranked[:3])
    if d < CLOSE:
        verdict = "USE" if d < CERTAIN else "USE+MENTION"
        head = with_alpha(g, c[3], major) if c[3] < 1 else label(g)
        res.update(verdict=verdict, token=with_alpha(g, c[3], major) if c[3] < 1 else g["names"][0][1], dE=round(d, 2))
        txt = f"{raw} -> {head}  dE {d:.1f}  {'certain' if d < CERTAIN else 'close: mention it'}"
        if d >= CERTAIN and c[3] >= 1:
            alt = opacity_match(target, groups, bg, bg_hex, STEPS)
            if alt and alt[0] < CERTAIN and alt[0] < d:
                txt += f"\n    better: {with_alpha(alt[1], alt[2], major)} over {bg_label}  dE {alt[0]:.1f} - pick by meaning"
                res["alternative"] = {"token": with_alpha(alt[1], alt[2], major), "dE": round(alt[0], 2)}
    else:
        best = opacity_match(target, groups, bg, bg_hex, STEPS)
        fine = opacity_match(target, groups, bg, bg_hex, FINE)
        pick = None
        if best and best[0] < CLOSE:
            pick = best
        elif fine and fine[0] < CLOSE:
            pick = fine
        if pick:
            od, og, a = pick
            verdict = "USE" if od < CERTAIN else "USE+MENTION"
            tok = with_alpha(og, a, major)
            res.update(verdict=verdict, token=tok, dE=round(od, 2), over=bg_hex)
            txt = (f"{raw} -> {tok} over {bg_label}  dE {od:.1f}  "
                   f"{'certain' if od < CERTAIN else 'close: mention it'}")
            if "[" in tok:
                txt += "  (arbitrary opacity: check the project allows it, else nearest step " \
                       f"{tw_alpha(round(a * 20) / 20 or 0.05, major)})"
        else:
            res.update(verdict="ASK", dE=round(d, 2))
            od = f"; best opacity {with_alpha(best[1], best[2], major)} dE {best[0]:.1f}" if best else ""
            txt = (f"{raw} -> ASK the user: no token within dE 5. Nearest: {nearest}{od}. "
                   f"Offer: use the nearest token, or tell me which token. Do not add a colour.")
    res["nearest"] = [{"token": x["names"][0][1], "hex": x["hex"], "dE": round(dd, 2)} for dd, x in ranked[:3]]

    # the project's default-palette colours (not recommended unless the project's rules allow them)
    dg = defaults_groups(data, theme)
    if dg and res.get("verdict") in ("ASK", "USE+MENTION"):
        dd, dgx = min(((delta_e2000(target, x["rgba"]), x) for x in dg if x["rgba"]), key=lambda t: t[0])
        if dd < CERTAIN and dd < res.get("dE", 99):
            uses = sum(dgx["names"][0][2].get("classes", {}).values())
            txt += (f"\n    note: Tailwind default {dgx['names'][0][1]} matches (dE {dd:.1f}, used {uses}x in the "
                    f"project) - not a project token; use only if the project's rules allow default colours")
            res["default_palette"] = {"token": dgx["names"][0][1], "dE": round(dd, 2)}

    # dark-theme value of the chosen token
    if data["themes"].get("has_dark") and res.get("token"):
        base = res["token"].split("/")[0]
        e = data["colors"]["tailwind"].get(base) or data["colors"]["vars"].get(base)
        dk = e.get("dark") if e else None
        txt += f"\n    dark: {dk['hex']}" if dk and "hex" in dk else "\n    dark: no dark value - check it reads on the dark background"
    if show_contrast:
        ratio = contrast(c, bg)
        aa = "AA ok" if ratio >= 4.5 else ("AA large-text only (>=24px or >=18.66px bold)" if ratio >= 3 else "FAILS AA as text")
        txt += f"\n    contrast as text on {bg_hex}: {ratio:.2f}:1 ({aa})"
        res["contrast"] = round(ratio, 2)
    res["text"] = txt
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description="Nearest project tokens for colours by Delta E 2000")
    ap.add_argument("--tokens", required=True)
    ap.add_argument("--colors", required=True, help='comma list: "#0a5f38,rgb(1 2 3),hsl(...)"')
    ap.add_argument("--background", help="background the colours sit on (default: the background token)")
    ap.add_argument("--theme", choices=["light", "dark"], default="light")
    ap.add_argument("--include-defaults", action="store_true",
                    help="also match Tailwind default-palette colours the project already uses")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    data = json.loads(Path(a.tokens).read_text(encoding="utf-8"))
    groups = load_groups(data, a.theme, a.include_defaults)
    bg, bg_label = find_background(data, a.theme, a.background)
    results = [match_one(x, groups, data, a.theme, bg, bg_label, bool(a.background))
               for x in split_colors(a.colors)]
    if a.json:
        print(json.dumps(results, indent=1))
    else:
        print(f"{len(groups)} token colours ({a.theme}), background {bg_label}")
        for r in results:
            print(r["text"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
