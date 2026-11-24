"""Shared colour helpers for screencraft scripts (stdlib only).

parse_color(str) -> (r, g, b, a) floats, r/g/b in 0..255, a in 0..1, or None.
Supports: #rgb #rgba #rrggbb #rrggbbaa, rgb()/rgba() (comma or space syntax, / alpha),
hsl()/hsla(), hwb(), oklch(), oklab(), lab(), lch(), a few named colours, and bare
channel triples ("10 95 56", "222.2 47.4% 11.2%") via parse_channels().
"""
from __future__ import annotations

import math
import re

NAMED = {
    "white": (255, 255, 255), "black": (0, 0, 0), "red": (255, 0, 0), "green": (0, 128, 0),
    "blue": (0, 0, 255), "gray": (128, 128, 128), "grey": (128, 128, 128),
    "yellow": (255, 255, 0), "orange": (255, 165, 0), "purple": (128, 0, 128),
    "silver": (192, 192, 192), "navy": (0, 0, 128), "teal": (0, 128, 128),
}

_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?"
HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})\b")
FUNC_RE = re.compile(r"\b(rgba?|hsla?|hwb|oklch|oklab|lab|lch)\(\s*([^()]*?)\s*\)", re.I)


def _clamp(x, lo=0.0, hi=255.0):
    return max(lo, min(hi, x))


def _num(tok: str, pct_scale: float = 1.0) -> float:
    tok = tok.strip()
    if tok.endswith("%"):
        return float(tok[:-1]) / 100.0 * pct_scale
    for unit, mul in (("deg", 1.0), ("grad", 0.9), ("rad", 180 / math.pi), ("turn", 360.0)):
        if tok.endswith(unit):
            return float(tok[: -len(unit)]) * mul
    if tok.lower() == "none":
        return 0.0
    return float(tok)


def _split_args(body: str):
    body = body.replace(",", " ")
    alpha = None
    if "/" in body:
        body, a = body.split("/", 1)
        alpha = a.strip()
    parts = body.split()
    return parts, alpha


def _alpha(a):
    if a is None:
        return 1.0
    return _clamp(_num(a, 1.0), 0.0, 1.0)


def _hsl_to_rgb(h, s, l):
    h = (h % 360) / 360.0
    if s == 0:
        v = l * 255
        return v, v, v

    def hue(p, q, t):
        t %= 1
        if t < 1 / 6:
            return p + (q - p) * 6 * t
        if t < 1 / 2:
            return q
        if t < 2 / 3:
            return p + (q - p) * (2 / 3 - t) * 6
        return p

    q = l * (1 + s) if l < 0.5 else l + s - l * s
    p = 2 * l - q
    return hue(p, q, h + 1 / 3) * 255, hue(p, q, h) * 255, hue(p, q, h - 1 / 3) * 255


def _lin_to_srgb(c):
    c = max(0.0, min(1.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def _srgb_to_lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _oklab_to_rgb(L, a, b):
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    r = 4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_
    g = -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_
    bb = -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_
    return tuple(_lin_to_srgb(v) * 255 for v in (r, g, bb))


def _lab_to_rgb(L, a, b):
    # CIE Lab (D50, as CSS lab()) -> XYZ D50 -> D65 -> sRGB
    fy = (L + 16) / 116
    fx = fy + a / 500
    fz = fy - b / 200
    e, k = 216 / 24389, 24389 / 27

    def f_inv(t):
        return t ** 3 if t ** 3 > e else (116 * t - 16) / k

    xr, yr, zr = f_inv(fx), (fy ** 3 if L > k * e else L / k), f_inv(fz)
    X, Y, Z = xr * 0.96422, yr * 1.0, zr * 0.82521
    # Bradford D50 -> D65
    X2 = 0.9554734527 * X - 0.0230985368 * Y + 0.0632593086 * Z
    Y2 = -0.0283697093 * X + 1.0099954580 * Y + 0.0210413990 * Z
    Z2 = 0.0123140016 * X - 0.0205076964 * Y + 1.3303659366 * Z
    r = 3.2409699419 * X2 - 1.5373831776 * Y2 - 0.4986107603 * Z2
    g = -0.9692436363 * X2 + 1.8759675015 * Y2 + 0.0415550574 * Z2
    bb = 0.0556300797 * X2 - 0.2039769589 * Y2 + 1.0569715142 * Z2
    return tuple(_lin_to_srgb(v) * 255 for v in (r, g, bb))


def parse_hex(h: str):
    h = h.lstrip("#")
    if len(h) in (3, 4):
        h = "".join(c * 2 for c in h)
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
    return float(r), float(g), float(b), a


def _func_to_rgba(fn: str, body: str):
    fn = fn.lower()
    parts, a = _split_args(body)
    if len(parts) < 3:
        return None
    if len(parts) == 4 and a is None:
        a = parts[3]
    try:
        if fn in ("rgb", "rgba"):
            r, g, b = (_num(p, 255.0) for p in parts[:3])
            rgb = (r, g, b)
        elif fn in ("hsl", "hsla"):
            h = _num(parts[0])
            s = _num(parts[1] if parts[1].endswith("%") else parts[1] + "%")
            l = _num(parts[2] if parts[2].endswith("%") else parts[2] + "%")
            rgb = _hsl_to_rgb(h, s, l)
        elif fn == "hwb":
            h, w, bl = _num(parts[0]), _num(parts[1]), _num(parts[2])
            if w + bl >= 1:
                v = w / (w + bl) * 255
                rgb = (v, v, v)
            else:
                r, g, b = _hsl_to_rgb(h, 1, 0.5)
                rgb = tuple(c * (1 - w - bl) + w * 255 for c in (r, g, b))
        elif fn == "oklch":
            L = _num(parts[0], 1.0)
            C = _num(parts[1], 0.4)
            H = math.radians(_num(parts[2]))
            rgb = _oklab_to_rgb(L, C * math.cos(H), C * math.sin(H))
        elif fn == "oklab":
            rgb = _oklab_to_rgb(_num(parts[0], 1.0), _num(parts[1], 0.4), _num(parts[2], 0.4))
        elif fn == "lab":
            rgb = _lab_to_rgb(_num(parts[0], 100.0), _num(parts[1], 125.0), _num(parts[2], 125.0))
        elif fn == "lch":
            L, C, H = _num(parts[0], 100.0), _num(parts[1], 150.0), math.radians(_num(parts[2]))
            rgb = _lab_to_rgb(L, C * math.cos(H), C * math.sin(H))
        else:
            return None
    except ValueError:
        return None
    r, g, b = (_clamp(c) for c in rgb)
    return r, g, b, _alpha(a)


def parse_color(s: str):
    """Parse one complete colour string. Returns (r,g,b,a) or None."""
    if s is None:
        return None
    s = s.strip().rstrip(";").strip()
    if s.startswith("!"):
        return None
    low = s.lower()
    if low in NAMED:
        r, g, b = NAMED[low]
        return float(r), float(g), float(b), 1.0
    if low == "transparent":
        return 0.0, 0.0, 0.0, 0.0
    m = HEX_RE.fullmatch(s)
    if m:
        return parse_hex(s)
    m = FUNC_RE.fullmatch(s)
    if m:
        return _func_to_rgba(m.group(1), m.group(2))
    return None


def parse_channels(s: str, fn_hint: str | None = None):
    """Bare channel triples used inside rgb(var(--x)) / hsl(var(--x)) patterns.

    Returns ((r,g,b,a), 'rgb'|'hsl'|'oklch') or None.
    """
    s = s.strip()
    parts, a = _split_args(s)
    if len(parts) != 3:
        return None
    if not all(re.fullmatch(_NUM + r"(?:%|deg)?", p) for p in parts):
        return None
    fn = fn_hint
    if fn is None:
        if parts[1].endswith("%") and parts[2].endswith("%"):
            fn = "hsl"
        elif all(not p.endswith("%") for p in parts) and all(0 <= float(p) <= 255 for p in parts) \
                and any(float(p) > 1 for p in parts):
            fn = "rgb"
        else:
            return None
    rgba = _func_to_rgba(fn, s)
    return (rgba, fn) if rgba else None


def to_hex(rgba) -> str:
    r, g, b, a = rgba
    out = "#{:02x}{:02x}{:02x}".format(round(r), round(g), round(b))
    if a < 0.999:
        out += "{:02x}".format(round(a * 255))
    return out


def composite(fg, bg):
    """Alpha-composite fg (r,g,b,a) over opaque bg (r,g,b,_) in sRGB space, as browsers do."""
    a = fg[3]
    return tuple(fg[i] * a + bg[i] * (1 - a) for i in range(3)) + (1.0,)


# ---- Delta E 2000 -------------------------------------------------------------

def rgb_to_lab(rgba):
    r, g, b = (_srgb_to_lin(c / 255.0) for c in rgba[:3])
    X = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    Y = (0.2126729 * r + 0.7151522 * g + 0.0721750 * b) / 1.0
    Z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116

    fx, fy, fz = f(X), f(Y), f(Z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e2000(c1, c2) -> float:
    L1, a1, b1 = rgb_to_lab(c1)
    L2, a2, b2 = rgb_to_lab(c2)
    C1, C2 = math.hypot(a1, b1), math.hypot(a2, b2)
    Cb = (C1 + C2) / 2
    G = 0.5 * (1 - math.sqrt(Cb ** 7 / (Cb ** 7 + 25 ** 7)))
    a1p, a2p = a1 * (1 + G), a2 * (1 + G)
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360
    h2p = math.degrees(math.atan2(b2, a2p)) % 360
    dLp = L2 - L1
    dCp = C2p - C1p
    if C1p * C2p == 0:
        dhp = 0
    elif abs(h2p - h1p) <= 180:
        dhp = h2p - h1p
    elif h2p - h1p > 180:
        dhp = h2p - h1p - 360
    else:
        dhp = h2p - h1p + 360
    dHp = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dhp / 2))
    Lbp = (L1 + L2) / 2
    Cbp = (C1p + C2p) / 2
    if C1p * C2p == 0:
        hbp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hbp = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        hbp = (h1p + h2p + 360) / 2
    else:
        hbp = (h1p + h2p - 360) / 2
    T = (1 - 0.17 * math.cos(math.radians(hbp - 30)) + 0.24 * math.cos(math.radians(2 * hbp))
         + 0.32 * math.cos(math.radians(3 * hbp + 6)) - 0.20 * math.cos(math.radians(4 * hbp - 63)))
    dtheta = 30 * math.exp(-(((hbp - 275) / 25) ** 2))
    Rc = 2 * math.sqrt(Cbp ** 7 / (Cbp ** 7 + 25 ** 7))
    Sl = 1 + (0.015 * (Lbp - 50) ** 2) / math.sqrt(20 + (Lbp - 50) ** 2)
    Sc = 1 + 0.045 * Cbp
    Sh = 1 + 0.015 * Cbp * T
    Rt = -math.sin(math.radians(2 * dtheta)) * Rc
    return math.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh))


# ---- WCAG contrast --------------------------------------------------------------

def luminance(rgba) -> float:
    r, g, b = (_srgb_to_lin(c / 255.0) for c in rgba[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg, bg) -> float:
    if fg[3] < 1:
        fg = composite(fg, bg)
    l1, l2 = luminance(fg), luminance(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def split_colors(s: str):
    """Split 'a,b,rgb(1,2,3)' on commas outside parentheses."""
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            if cur.strip():
                out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out
