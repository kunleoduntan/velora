"""Theme engine: a few seed choices in, a complete accessible design system out.

    ThemeSpec (brand, accent, radius, density, font, mode...)          what an admin chooses
         │  compile_theme()
         ▼
    tokens for LIGHT and DARK (derived, never hand-written)  +  CSS  +  WCAG audit  +  Excel palette

Every text/background pair that matters is checked and *corrected by construction*: a brand colour that would make white
button text unreadable is tuned (smallest lightness shift) or given dark text; muted text, links and status colours are
pushed to >= 4.5:1 on every surface they appear on. The audit proves it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..exceptions import ValidationError
from . import color as c

_PRESETS = json.loads((Path(__file__).parent / "presets.json").read_text())["presets"]
PRESETS = {p["name"]: p for p in _PRESETS}
DEFAULT_PRESET = "velora"

RADII = {"square": ("2px", "4px"), "soft": ("6px", "10px"), "round": ("12px", "18px")}
DENSITIES = {
    "compact": {"--cell-py": "3px", "--control-h": "28px", "--btn-py": "3px", "--gap": "8px", "--font-size": "13px"},
    "comfortable": {"--cell-py": "5px", "--control-h": "32px", "--btn-py": "5px", "--gap": "12px", "--font-size": "14px"},
    "spacious": {"--cell-py": "9px", "--control-h": "38px", "--btn-py": "8px", "--gap": "16px", "--font-size": "15px"},
}
FONTS = {
    "system": '"Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif',
    "rounded": 'ui-rounded, "SF Pro Rounded", "Nunito", "Segoe UI", system-ui, sans-serif',
    "classic": 'Arial, "Helvetica Neue", Helvetica, sans-serif',
}
MODES = ("light", "dark", "system")
_KEYS = {"preset", "brand", "accent", "radius", "density", "font", "default_mode", "allow_user_override", "brand_name"}


class ThemeError(ValidationError):
    pass


@dataclass
class ThemeSpec:
    preset: str = DEFAULT_PRESET
    brand: str | None = None            # overrides the preset's brand colour
    accent: str | None = None           # secondary highlight; defaults to a hue-shifted brand
    radius: str = "square"
    density: str = "comfortable"
    font: str = "system"
    default_mode: str | None = None     # None -> the preset's own (e.g. Midnight is dark)
    allow_user_override: bool = True
    brand_name: str = ""

    @classmethod
    def from_dict(cls, d: dict | None) -> "ThemeSpec":
        d = dict(d or {})
        errors = []
        unknown = sorted(set(d) - _KEYS)
        if unknown:
            errors.append(f"unknown setting(s): {', '.join(unknown)}")
        spec = cls()
        spec.preset = d.get("preset", DEFAULT_PRESET)
        if not isinstance(spec.preset, str) or spec.preset not in PRESETS:
            errors.append(f"unknown preset {spec.preset!r} (choose from: {', '.join(PRESETS)})")
        for key in ("brand", "accent"):
            if d.get(key):
                try:
                    setattr(spec, key, c.normalize_hex(str(d[key])))
                except c.ColorError as e:
                    errors.append(f"{key}: {e}")
        for key, allowed in (("radius", RADII), ("density", DENSITIES), ("font", FONTS)):
            v = d.get(key, getattr(spec, key))
            if not isinstance(v, str) or v not in allowed:
                errors.append(f"{key} must be one of {', '.join(allowed)}")
            else:
                setattr(spec, key, v)
        if d.get("default_mode") is not None:
            if not isinstance(d["default_mode"], str) or d["default_mode"] not in MODES:
                errors.append(f"default_mode must be one of {', '.join(MODES)}")
            else:
                spec.default_mode = d["default_mode"]
        spec.allow_user_override = bool(d.get("allow_user_override", True))
        name = str(d.get("brand_name", "") or "")
        if len(name) > 60 or any(ord(ch) < 32 for ch in name):
            errors.append("brand_name must be at most 60 characters with no control characters")
        spec.brand_name = name.strip()
        if errors:
            raise ThemeError("Invalid theme: " + "; ".join(errors), details=errors)
        return spec

    def to_dict(self) -> dict:
        return {"preset": self.preset, "brand": self.brand, "accent": self.accent, "radius": self.radius, "density": self.density,
                "font": self.font, "default_mode": self.default_mode, "allow_user_override": self.allow_user_override, "brand_name": self.brand_name}


@dataclass
class CompiledTheme:
    spec: dict
    tokens: dict           # {"light": {...}, "dark": {...}}
    css: str
    audit: list            # every contrast pair checked
    passed: bool
    excel: dict            # palette for spreadsheets (hex without '#')
    default_mode: str
    brand: str

    def to_dict(self) -> dict:
        return {"spec": self.spec, "tokens": self.tokens, "css": self.css, "audit": self.audit, "passed": self.passed,
                "excel": self.excel, "default_mode": self.default_mode, "brand": self.brand}


_SEMANTIC = {"ok": ("#16a34a", 150), "warn": ("#d97706", 75), "danger": ("#dc2626", 27), "info": ("#2563eb", 255)}


def _build_mode(brand: str, accent: str, nh: float, nc: float, dark: bool) -> tuple[dict, list]:
    N = lambda L, k=1.0: c.oklch_to_hex(L, nc * k, nh)
    Lb, Cb, hb = c.hex_to_oklch(brand)
    audit: list = []

    def chk(pair, fg, bg, required=4.5):
        r = c.contrast(fg, bg)
        audit.append({"mode": "dark" if dark else "light", "pair": pair, "fg": fg, "bg": bg, "ratio": round(r, 2), "required": required, "pass": r >= required})

    if dark:
        surface, bg = N(.215), N(.17)
        header, line, line_strong, hover, zebra = N(.245), N(.30), N(.42), N(.26), N(.235)
        text = N(.94, .6)
        muted = c.ensure_contrast(N(.72), surface, bg, header)
        b_in = c.oklch_to_hex(min(max(Lb, .62), .80), Cb, hb)                       # brands are lightened on dark surfaces
        shadow = "0 6px 18px rgba(0,0,0,.5)"
    else:
        surface, bg = "#ffffff", N(.972)
        header, line, line_strong, hover, zebra = N(.955), N(.915), N(.80), N(.955), N(.982)
        text = N(.25, .6)
        muted = c.ensure_contrast(N(.50), surface, bg, header)
        b_in = brand
        shadow = "0 6px 18px rgba(0,0,0,.14)"

    on_brand, brand_fill = c.pick_on_color(b_in)
    Lf, Cf, hf = c.hex_to_oklch(brand_fill)
    hover_fill = c.oklch_to_hex(Lf + (.05 if dark else -.05), Cf, hf)
    if c.contrast(on_brand, hover_fill) < 4.5:
        hover_fill = brand_fill
    brand_soft = c.oklch_to_hex(.28 if dark else .955, min(Cb * .4, .06), hb)
    sel = c.oklch_to_hex(.34 if dark else .91, min(Cb * .55, .08), hb)
    brand_text = c.ensure_contrast(brand_fill, surface, brand_soft, bg, header)
    ring = c.ensure_contrast(brand_fill, surface, bg, target=3.0)
    a_text, a_fill = c.pick_on_color(c.oklch_to_hex(min(max(c.hex_to_oklch(accent)[0], .62), .80), c.hex_to_oklch(accent)[1], c.hex_to_oklch(accent)[2]) if dark else accent)
    a_soft = c.oklch_to_hex(.28 if dark else .955, min(c.hex_to_oklch(accent)[1] * .4, .06), c.hex_to_oklch(accent)[2])

    t = {"--bg": bg, "--card": surface, "--header-bg": header, "--line": line, "--line-strong": line_strong, "--text": text, "--muted": muted,
         "--hover": hover, "--zebra": zebra, "--brand": brand_fill, "--brand-hover": hover_fill, "--on-brand": on_brand, "--brand-soft": brand_soft,
         "--brand-text": brand_text, "--sel": sel, "--ring": ring, "--accent": a_fill, "--on-accent": a_text, "--accent-soft": a_soft, "--shadow": shadow}
    chk("text on surface", text, surface, 7.0)
    chk("text on background", text, bg, 7.0)
    chk("muted text on surface", muted, surface)
    chk("muted text on background", muted, bg)
    chk("muted text on table header", muted, header)
    chk("button text on brand", on_brand, brand_fill)
    chk("button text on brand (hover)", on_brand, hover_fill)
    chk("brand link on surface", brand_text, surface)
    chk("brand text on soft brand", brand_text, brand_soft)
    chk("brand link on background", brand_text, bg)
    chk("accent button text", a_text, a_fill)
    chk("focus ring on surface", ring, surface, 3.0)
    for name, (seed, hue) in _SEMANTIC.items():
        Ls, Cs, _ = c.hex_to_oklch(seed)
        soft = c.oklch_to_hex(.28 if dark else .955, .05, hue)
        solid = c.ensure_contrast(c.oklch_to_hex(.76 if dark else Ls, Cs, hue), surface, soft, bg)
        t[f"--{name}"], t[f"--{name}-soft"] = solid, soft
        chk(f"{name} text on surface", solid, surface)
        chk(f"{name} text on its soft background", solid, soft)
    return t, audit


def excel_palette(brand: str, nh: float, nc: float) -> dict:
    """Soft, simple spreadsheet colours: pastel header tint with a deep brand-coloured text, a mid-tone rule, light section fills."""
    _, Cb, hb = c.hex_to_oklch(brand)
    pastel = lambda L, k: c.oklch_to_hex(L, min(Cb * k, .06), hb)
    header_bg = pastel(.925, .45)
    dark = c.oklch_to_hex(.36, min(Cb, .13), hb)
    p = {
        "title": c.ensure_contrast(dark, "#ffffff", target=7.0),
        "header_bg": header_bg,
        "header_text": c.ensure_contrast(dark, header_bg, target=7.0),
        "rule": c.oklch_to_hex(.64, min(Cb, .14), hb),               # the confident line under headers / above totals
        "section_bg": pastel(.962, .3),
        "total_bg": pastel(.94, .38),
        "band": c.oklch_to_hex(.983, nc, nh),
        "grid": c.oklch_to_hex(.90, nc, nh),
        "muted": c.ensure_contrast(c.oklch_to_hex(.5, nc, nh), "#ffffff", target=4.5),
        "text": c.oklch_to_hex(.25, nc * .6, nh),
    }
    return {k: v.lstrip("#") for k, v in p.items()}


def _css(spec: ThemeSpec, tokens: dict, font: str) -> str:
    def block(sel, d):
        return sel + "{" + ";".join(f"{k}:{v}" for k, v in d.items()) + "}"
    r, rl = RADII[spec.radius]
    base = {"--radius": r, "--radius-lg": rl, "--font": font, **DENSITIES[spec.density]}
    out = [block(':root,:root[data-theme="light"]', {**tokens["light"], **base}),
           block(':root[data-theme="dark"]', tokens["dark"]),
           "@media (prefers-color-scheme: dark){" + block(':root[data-theme="system"]', tokens["dark"]) + "}"]
    out += [block(f':root[data-density="{k}"]', v) for k, v in DENSITIES.items()]
    return "\n".join(out)


def compile_theme(spec: ThemeSpec | dict | None = None) -> CompiledTheme:
    spec = spec if isinstance(spec, ThemeSpec) else ThemeSpec.from_dict(spec)
    preset = PRESETS[spec.preset]
    brand = spec.brand or preset["brand"]
    accent = spec.accent or c.rotate_hue(brand, 40)
    nh, nc = float(preset["neutral_hue"]), float(preset["neutral_chroma"])
    if spec.brand:                                   # a custom brand colour re-tints the neutrals so the UI stays harmonious
        _, Cb, hb = c.hex_to_oklch(brand)
        nh, nc = hb, min(max(nc, .006), .012) if Cb > .02 else nc
    light, a1 = _build_mode(brand, accent, nh, nc, dark=False)
    dark, a2 = _build_mode(brand, accent, nh, nc, dark=True)
    tokens = {"light": light, "dark": dark}
    audit = a1 + a2
    return CompiledTheme(spec=spec.to_dict(), tokens=tokens, css=_css(spec, tokens, FONTS[spec.font]), audit=audit,
                         passed=all(a["pass"] for a in audit), excel=excel_palette(brand, nh, nc),
                         default_mode=spec.default_mode or preset["default_mode"], brand=c.normalize_hex(brand))


def list_presets() -> list[dict]:
    return [{k: p[k] for k in ("name", "label", "description", "brand", "default_mode", "source")} for p in _PRESETS]
