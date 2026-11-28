"""Perceptual colour maths (OKLCH) and WCAG contrast.

Why OKLCH: equal steps in lightness *look* equal across hues, so a palette generated from any brand colour has a
consistent tonal ramp, and we can adjust only lightness to reach a contrast target without shifting the hue.
"""
from __future__ import annotations

import math
import re

_HEX = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


class ColorError(ValueError):
    pass


def normalize_hex(value: str) -> str:
    m = _HEX.match((value or "").strip())
    if not m:
        raise ColorError(f"{value!r} is not a hex colour (use #RGB or #RRGGBB)")
    h = m.group(1).lower()
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return "#" + h


def hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = normalize_hex(h)[1:]
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def rgb_to_hex(r: float, g: float, b: float) -> str:
    return "#" + "".join(f"{round(max(0.0, min(1.0, c)) * 255):02x}" for c in (r, g, b))


def _to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _from_linear(c: float) -> float:
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def _rgb_to_oklab(r: float, g: float, b: float):
    r, g, b = _to_linear(r), _to_linear(g), _to_linear(b)
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def _oklab_to_rgb_linear(L: float, a: float, b: float):
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
            -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
            -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)


def hex_to_oklch(h: str) -> tuple[float, float, float]:
    L, a, b = _rgb_to_oklab(*hex_to_rgb(h))
    return L, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360


def oklch_to_hex(L: float, C: float, h: float) -> str:
    """Convert, reducing chroma (never lightness or hue) until the colour fits the sRGB gamut."""
    L = max(0.0, min(1.0, L))
    lo, hi = 0.0, max(C, 0.0)

    def conv(c):
        a, b = c * math.cos(math.radians(h)), c * math.sin(math.radians(h))
        return _oklab_to_rgb_linear(L, a, b)

    def inside(rgb):
        return all(-0.0005 <= v <= 1.0005 for v in rgb)

    if inside(conv(hi)):
        c = hi
    else:
        for _ in range(24):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if inside(conv(mid)) else (lo, mid)
        c = lo
    r, g, b = (_from_linear(max(0.0, min(1.0, v))) for v in conv(c))
    return rgb_to_hex(r, g, b)


def luminance(h: str) -> float:
    r, g, b = (_to_linear(c) for c in hex_to_rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def ensure_contrast(fg: str, *backgrounds: str, target: float = 4.5, prefer: str | None = None) -> str:
    """Return `fg` with only its lightness moved until it reaches `target`:1 against EVERY background.
    `prefer` ('darker'|'lighter') forces the direction; by default it moves away from the backgrounds' average luminance."""
    L, C, h = hex_to_oklch(fg)
    avg = sum(luminance(b) for b in backgrounds) / len(backgrounds)
    direction = -1 if (prefer == "darker" or (prefer is None and avg > 0.4)) else 1
    cur = normalize_hex(fg)
    for _ in range(120):
        if all(contrast(cur, b) >= target for b in backgrounds):
            return cur
        L += direction * 0.005
        if L < 0 or L > 1:
            break
        cur = oklch_to_hex(L, C, h)
    # unreachable in this direction (e.g. mid-grey on mid-grey): fall back to the extreme that works
    for extreme in ("#000000", "#ffffff"):
        if all(contrast(extreme, b) >= target for b in backgrounds):
            return extreme
    return cur


def with_lightness(h: str, L: float, chroma_scale: float = 1.0, chroma_max: float | None = None) -> str:
    _, C, hue = hex_to_oklch(h)
    C = C * chroma_scale
    if chroma_max is not None:
        C = min(C, chroma_max)
    return oklch_to_hex(L, C, hue)


def rotate_hue(h: str, degrees: float) -> str:
    L, C, hue = hex_to_oklch(h)
    return oklch_to_hex(L, C, (hue + degrees) % 360)


def pick_on_color(fill: str, target: float = 4.5, max_darken: float = 0.07, max_lighten: float = 0.10) -> tuple[str, str]:
    """Choose readable text for a solid `fill` (a button). Returns (text, fill).
    Convention first: WHITE text, deepening the fill slightly if needed (up to `max_darken`). If that would change the brand
    too much (light brands like cyan/amber), use near-black text instead, lightening the fill only if needed.
    A brand colour is never rejected - at most tuned by the smallest lightness shift that makes the text readable."""
    white, black = "#ffffff", "#111418"
    L, C, h = hex_to_oklch(fill)
    for step in range(0, int(max_darken / 0.005) + 1):
        cand = fill if step == 0 else oklch_to_hex(L - step * 0.005, C, h)
        if contrast(white, cand) >= target:
            return white, cand
    for step in range(0, int(max_lighten / 0.005) + 1):
        cand = fill if step == 0 else oklch_to_hex(L + step * 0.005, C, h)
        if contrast(black, cand) >= target:
            return black, cand
    return (white, fill) if contrast(white, fill) >= contrast(black, fill) else (black, fill)
