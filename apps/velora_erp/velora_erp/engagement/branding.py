"""The branded email layout. One table-based design that renders the same in Outlook, Gmail and phone mail apps.

Every piece of text that comes from a record or a person is HTML-escaped here, and nowhere else is HTML built from data.
"""
from __future__ import annotations

import re
from html import escape

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
EMBLEMS = {"Birthday": "\U0001F382", "Work Anniversary": "\U0001F3C6", "Partnership Anniversary": "\U0001F91D", "Holiday": "\U0001F389", "Win Back": "\U0001F44B", "Custom": "✨"}


def colour(value, fallback="#0f6cbd") -> str:
    return value if isinstance(value, str) and HEX.match(value) else fallback


def _shade(hex_colour: str, factor: float) -> str:
    """Lighten (factor > 0) or darken (factor < 0) a colour for the banner gradient."""
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    f = (lambda c: int(c + (255 - c) * factor)) if factor > 0 else (lambda c: int(c * (1 + factor)))
    return "#%02x%02x%02x" % (f(r), f(g), f(b))


def _para(text: str) -> str:
    return "".join(f'<p style="margin:0 0 16px;font-size:16px;line-height:1.65;color:#2d3748">{escape(p.strip()).replace(chr(10), "<br>")}</p>' for p in re.split(r"\n\s*\n", text or "") if p.strip())


def render_email(*, brand: str, logo_url: str = "", accent: str = "#0f6cbd", emblem: str = "", heading: str = "", body: str = "", button_label: str = "", button_url: str = "",
                 signature: str = "", unsubscribe_url: str = "", preheader: str = "") -> str:
    accent = colour(accent)
    dark, light = _shade(accent, -0.22), _shade(accent, 0.18)
    logo = (f'<img src="{escape(logo_url, quote=True)}" alt="{escape(brand, quote=True)}" height="40" style="display:block;margin:0 auto 10px;border:0;max-height:40px">'
            if logo_url.startswith("https://") else "")
    button = ""
    if button_label and button_url.startswith(("https://", "http://", "mailto:")):
        button = (f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:8px 0 24px"><tr><td style="border-radius:8px;background:{accent}">'
                  f'<a href="{escape(button_url, quote=True)}" style="display:inline-block;padding:13px 28px;font-size:16px;font-weight:600;color:#ffffff;text-decoration:none;border-radius:8px">{escape(button_label)}</a></td></tr></table>')
    sig = f'<p style="margin:24px 0 0;font-size:16px;line-height:1.6;color:#2d3748">{escape(signature).replace(chr(10), "<br>")}</p>' if signature else ""
    unsub = (f'<a href="{escape(unsubscribe_url, quote=True)}" style="color:#718096;text-decoration:underline">Unsubscribe</a>' if unsubscribe_url.startswith("http") else "")
    pre = f'<div style="display:none;max-height:0;overflow:hidden;opacity:0">{escape(preheader)}</div>' if preheader else ""
    return (
        '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>'
        f'<body style="margin:0;padding:0;background:#f1f4f8;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">{pre}'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f1f4f8"><tr><td align="center" style="padding:28px 12px">'
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:100%;max-width:600px;background:#ffffff;border-radius:14px;overflow:hidden;box-shadow:0 2px 12px rgba(15,35,70,.08)">'
        f'<tr><td align="center" style="background:{accent};background-image:linear-gradient(135deg,{dark},{light});padding:34px 28px 30px;color:#ffffff">{logo}'
        f'<div style="font-size:13px;letter-spacing:.14em;text-transform:uppercase;opacity:.9">{escape(brand)}</div>'
        f'<div style="font-size:44px;line-height:1.2;margin:14px 0 4px">{escape(emblem)}</div>'
        f'<div style="font-size:28px;line-height:1.25;font-weight:700">{escape(heading)}</div></td></tr>'
        f'<tr><td style="padding:34px 38px 30px">{_para(body)}{button}{sig}</td></tr>'
        f'<tr><td style="padding:18px 38px 26px;background:#f8fafc;border-top:1px solid #e8edf3;font-size:12px;line-height:1.6;color:#718096;text-align:center">'
        f'Sent with care by {escape(brand)}.{(" " + unsub) if unsub else ""}</td></tr>'
        '</table></td></tr></table></body></html>')
