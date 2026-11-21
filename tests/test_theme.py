import random
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import velora
from velora import db
from velora.api import create_app
from velora.settings import get_setting, set_setting
from velora.theme import PRESETS, ThemeError, ThemeSpec, compile_theme, color as c, current_excel_palette, current_theme

ADMIN = {"X-Velora-User": "boss", "X-Velora-Roles": "System Manager"}
SALES = {"X-Velora-User": "sam", "X-Velora-Roles": "Sales User"}


# ---------------- colour maths ----------------
def test_wcag_contrast_matches_published_reference_values():
    assert c.contrast("#000000", "#ffffff") == pytest.approx(21.0)
    assert c.contrast("#767676", "#ffffff") == pytest.approx(4.54, abs=0.01)         # the classic AA boundary grey
    assert c.contrast("#ffffff", "#ffffff") == pytest.approx(1.0)


def test_oklch_round_trip_is_lossless_for_in_gamut_colours():
    for h in ("#0f6cbd", "#e91e8c", "#00f0ff", "#6c5ce7", "#22c55e", "#808080", "#ffffff", "#000000", "#123456"):
        assert c.oklch_to_hex(*c.hex_to_oklch(h)) == h


def test_out_of_gamut_requests_lose_chroma_not_lightness_or_hue():
    out = c.oklch_to_hex(0.9, 0.4, 150)                                              # far outside sRGB
    L, C, hue = c.hex_to_oklch(out)
    assert L == pytest.approx(0.9, abs=0.01) and C < 0.4 and hue == pytest.approx(150, abs=3)


@pytest.mark.parametrize("bad", ["red", "#12", "#gggggg", "", "#12345", "12345678"])
def test_hex_validation(bad):
    with pytest.raises(c.ColorError):
        c.normalize_hex(bad)
    assert c.normalize_hex("ABC") == "#aabbcc" and c.normalize_hex("#0F6CBD") == "#0f6cbd"


def test_pick_on_color_prefers_white_text_and_tunes_the_fill_minimally():
    text, fill = c.pick_on_color("#0f6cbd")
    assert text == "#ffffff" and fill == "#0f6cbd"                                   # already fine: untouched
    text, fill = c.pick_on_color("#e91e8c")                                          # white is 4.18:1 -> deepen slightly
    assert text == "#ffffff" and c.contrast(text, fill) >= 4.5 and abs(c.hex_to_oklch(fill)[0] - c.hex_to_oklch("#e91e8c")[0]) < 0.07
    text, fill = c.pick_on_color("#00f0ff")                                          # far too light for white: dark text instead
    assert text != "#ffffff" and fill == "#00f0ff" and c.contrast(text, fill) >= 4.5


def test_ensure_contrast_changes_only_lightness_and_meets_every_background():
    out = c.ensure_contrast("#6ee7b7", "#ecfdf5", "#ffffff")
    assert c.contrast(out, "#ecfdf5") >= 4.5 and c.contrast(out, "#ffffff") >= 4.5
    assert c.hex_to_oklch(out)[2] == pytest.approx(c.hex_to_oklch("#6ee7b7")[2], abs=4)       # same hue family
    assert c.ensure_contrast("#222222", "#ffffff") == "#222222"                       # already readable: unchanged
    dark = c.ensure_contrast("#555555", "#111111")                                    # on a dark background it moves lighter
    assert c.luminance(dark) > c.luminance("#555555")


# ---------------- the accessibility guarantee ----------------
def test_every_preset_passes_the_wcag_audit_in_light_and_dark():
    for name in PRESETS:
        ct = compile_theme({"preset": name})
        bad = [a for a in ct.audit if not a["pass"]]
        assert ct.passed and not bad, (name, bad[:2])
        assert {a["mode"] for a in ct.audit} == {"light", "dark"} and len(ct.audit) >= 36


def test_ANY_brand_colour_produces_an_accessible_theme():
    rnd = random.Random(1234)
    seeds = ["#000000", "#ffffff", "#ffff00", "#00f0ff", "#ff00ff", "#808080", "#7f7f7f", "#fefefe", "#010101"]
    seeds += [f"#{rnd.randrange(0x1000000):06x}" for _ in range(300)]
    failures = []
    for seed in seeds:
        ct = compile_theme({"brand": seed})
        failures += [(seed, a["pair"], a["mode"], a["ratio"]) for a in ct.audit if not a["pass"]]
    assert failures == []


def test_the_vic_problem_cases_are_fixed_by_construction():
    """From the audit of the original theme: white-on-accent as low as 1.41:1 (Electric) and 1.5-2.7:1 on dark Emerald/Verdant/Cyan..."""
    for name in ("electric", "emerald", "verdant", "cyan", "mint", "sunset", "ember", "forest", "farepoint"):
        for mode in ("light", "dark"):
            t = compile_theme({"preset": name}).tokens[mode]
            assert c.contrast(t["--on-brand"], t["--brand"]) >= 4.5, (name, mode)
            assert c.contrast(t["--muted"], t["--card"]) >= 4.5 and c.contrast(t["--brand-text"], t["--card"]) >= 4.5
    e = compile_theme({"preset": "electric"}).tokens["light"]
    assert e["--on-brand"] != "#ffffff" and e["--brand"] == "#00f0ff"                # keeps the neon, switches the text


def test_dark_mode_is_derived_with_raised_surfaces_not_inverted():
    t = compile_theme({"preset": "velora"}).tokens
    lum = lambda h: c.luminance(h)
    d = t["dark"]
    assert lum(d["--bg"]) < lum(d["--card"]) < lum(d["--header-bg"]) < lum(d["--hover"]) < 0.05       # elevation = lighter
    assert lum(t["light"]["--bg"]) < lum(t["light"]["--card"]) == 1.0
    assert lum(d["--text"]) > 0.7 > lum(d["--muted"]) > lum(d["--line-strong"])


# ---------------- spec validation + output ----------------
def test_spec_reports_every_problem_at_once():
    with pytest.raises(ThemeError) as e:
        ThemeSpec.from_dict({"preset": "nope", "brand": "red", "radius": "pointy", "density": "tiny", "font": "comic", "default_mode": "sepia",
                             "brand_name": "x" * 99, "bogus": 1})
    msg = str(e.value)
    for frag in ("unknown preset", "brand:", "radius", "density", "font", "default_mode", "brand_name", "unknown setting"):
        assert frag in msg, frag
    assert len(e.value.details) == 8


def test_spec_defaults_and_round_trip():
    s = ThemeSpec.from_dict({})
    assert (s.preset, s.radius, s.density, s.font, s.allow_user_override) == ("velora", "square", "comfortable", "system", True)
    assert ThemeSpec.from_dict(s.to_dict()).to_dict() == s.to_dict()
    assert ThemeSpec.from_dict({"brand": "ABC"}).brand == "#aabbcc"
    with pytest.raises(ThemeError):
        ThemeSpec.from_dict({"brand_name": "bad\x07name"})


def test_compiled_css_structure():
    ct = compile_theme({"preset": "ocean", "radius": "round", "density": "compact", "font": "rounded"})
    css = ct.css
    assert ':root,:root[data-theme="light"]{' in css and ':root[data-theme="dark"]{' in css
    assert '@media (prefers-color-scheme: dark){:root[data-theme="system"]{' in css            # follow the OS when mode = system
    for d in ("compact", "comfortable", "spacious"):
        assert f':root[data-density="{d}"]' in css                                              # users can override density per device
    assert "--radius:12px" in css and "ui-rounded" in css and "--cell-py:3px" in css
    assert "!important" not in css
    for tok in ("--bg", "--card", "--text", "--muted", "--brand", "--on-brand", "--brand-text", "--danger", "--ok", "--warn", "--info", "--ring", "--zebra"):
        assert tok in ct.tokens["light"] and tok in ct.tokens["dark"]
    assert all(re.fullmatch(r"#[0-9a-f]{6}", v) for k, v in ct.tokens["light"].items() if k not in ("--shadow",))
    assert compile_theme({"preset": "ocean", "radius": "round", "density": "compact", "font": "rounded"}).css == css       # deterministic


def test_presets_include_all_fifteen_vic_themes_plus_velora_originals():
    vic = {"violet", "farepoint", "emerald", "sunset", "ocean", "nova", "ember", "midnight", "verdant", "arctic", "forest", "candy", "cyan", "mint", "electric"}
    assert vic <= set(PRESETS) and {"velora", "graphite", "ledger"} <= set(PRESETS)
    assert compile_theme({"preset": "midnight"}).default_mode == "dark" and compile_theme({"preset": "velora"}).default_mode == "system"
    assert compile_theme({"preset": "velora", "default_mode": "light"}).default_mode == "light"


def test_custom_brand_overrides_the_preset_and_retints():
    a, b = compile_theme({"preset": "velora"}), compile_theme({"brand": "#7a3cff"})
    assert a.tokens["light"]["--brand"] != b.tokens["light"]["--brand"] and b.brand == "#7a3cff"
    assert a.excel["header_bg"] != b.excel["header_bg"]


def test_excel_palette_is_readable_and_soft():
    for name in PRESETS:
        p = {k: "#" + v for k, v in compile_theme({"preset": name}).excel.items()}
        assert c.contrast(p["header_text"], p["header_bg"]) >= 7 and c.contrast(p["title"], "#ffffff") >= 7
        assert c.contrast(p["muted"], "#ffffff") >= 4.5 and c.contrast(p["text"], p["total_bg"]) >= 7
        assert c.hex_to_oklch(p["header_bg"])[0] > 0.88 and c.hex_to_oklch(p["section_bg"])[0] > 0.94   # pastel: light + low chroma
        assert c.hex_to_oklch(p["header_bg"])[1] <= 0.065


# ---------------- settings + API ----------------
def test_settings_round_trip_upsert_and_tolerate_an_unmigrated_site(site):
    with db.transaction():
        assert get_setting("theme") is None and get_setting("theme", {"x": 1}) == {"x": 1}
        set_setting("theme", {"preset": "ledger"})
        assert get_setting("theme") == {"preset": "ledger"}
        set_setting("theme", {"preset": "mint"})                                  # second write updates, never duplicates
        assert get_setting("theme") == {"preset": "mint"}
        assert db.conn().execute(text("select count(*) from velora_setting")).scalar() == 1
        assert current_theme().brand == compile_theme({"preset": "mint"}).brand
    with db.transaction() as conn:
        conn.execute(text("DROP TABLE velora_setting"))
        assert get_setting("theme", "fallback") == "fallback"                      # a site that has not run migrate yet still works


def test_a_corrupt_stored_theme_never_breaks_the_app(site):
    with db.transaction():
        set_setting("theme", {"preset": "does-not-exist", "radius": 5})
        assert current_theme().passed and current_excel_palette()["header_bg"]       # falls back to the default theme


@pytest.fixture
def client(site):
    return TestClient(create_app(auto_init=False))


def test_theme_api_read_edit_and_permissions(client):
    r = client.get("/api/theme", headers=SALES).json()["data"]
    assert r["passed"] is True and r["can_edit"] is False and len(r["presets"]) == 18 and r["spec"]["preset"] == "velora"
    assert client.put("/api/theme", json={"preset": "ledger"}, headers=SALES).status_code == 403
    assert client.post("/api/theme/preview", json={"preset": "ledger"}, headers=SALES).status_code == 403
    r = client.put("/api/theme", json={"preset": "ledger", "radius": "soft", "brand_name": "Velora Technologies"}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["data"]["spec"]["radius"] == "soft"
    got = client.get("/api/theme", headers=SALES).json()["data"]                      # everyone sees the saved theme
    assert got["spec"]["preset"] == "ledger" and got["spec"]["brand_name"] == "Velora Technologies" and "--radius:6px" in got["css"]


def test_theme_api_validates_and_preview_does_not_save(client):
    r = client.put("/api/theme", json={"brand": "notacolour", "radius": "x"}, headers=ADMIN)
    assert r.status_code == 422 and r.json()["error"] == "ThemeError" and len(r.json()["details"]) == 2
    prev = client.post("/api/theme/preview", json={"preset": "farepoint"}, headers=ADMIN).json()["data"]
    assert prev["brand"] == "#e91e8c" and prev["passed"]
    assert client.get("/api/theme", headers=ADMIN).json()["data"]["spec"]["preset"] == "velora"          # nothing was stored
    assert client.get("/api/theme").status_code == 401                                                      # per-site theme needs sign-in


def test_public_theme_needs_no_sign_in_and_exposes_no_company_data(client):
    r = client.get("/api/theme/public")
    assert r.status_code == 200 and set(r.json()["data"]) == {"css", "default_mode", "brand", "spec"}
    assert ":root" in r.json()["data"]["css"]
