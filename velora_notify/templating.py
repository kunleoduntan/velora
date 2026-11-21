"""Message templates (Jinja2, sandboxed): `Invoice {{ doc.name }} for {{ doc.grand_total|money }} is due {{ doc.due_date|date }}`.

The sandbox blocks attribute tricks (`''.__class__`), imports and calls to anything but what we hand it; templates are length-limited, and output is capped."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from jinja2 import TemplateSyntaxError, Undefined
from jinja2.sandbox import SandboxedEnvironment, SecurityError, safe_range

MAX_TEMPLATE, MAX_OUTPUT = 5000, 20000
MAX_BROADCAST = 200000                              # a designed HTML email is far longer than a notification line


class TemplateError(ValueError):
    pass


def _money(v, places: int = 2):
    try:
        return f"{Decimal(str(v)):,.{places}f}"
    except (InvalidOperation, ValueError):
        return "" if v in (None, "") else str(v)


def _date(v, fmt: str = "%d %b %Y"):
    if isinstance(v, datetime):
        return v.strftime(fmt)
    if isinstance(v, date):
        return v.strftime(fmt)
    try:
        return date.fromisoformat(str(v)[:10]).strftime(fmt)
    except ValueError:
        return "" if v in (None, "") else str(v)


def _env(html: bool) -> SandboxedEnvironment:
    env = SandboxedEnvironment(autoescape=html, undefined=Undefined, trim_blocks=True, lstrip_blocks=True, finalize=lambda v: "" if v is None else v)   # a missing value prints nothing, never "None"
    env.filters.update(money=_money, date=_date)
    env.globals.clear()                                   # no lipsum/cycler/namespace/dict: less surface to attack
    env.globals["range"] = safe_range                     # the sandbox's own range(), capped at 100,000
    return env


TEXT, HTML = _env(False), _env(True)


def validate(src: str, limit: int = MAX_TEMPLATE) -> None:
    if len(src or "") > limit:
        raise TemplateError(f"A template can be at most {limit} characters")
    try:
        TEXT.parse(src or "")
    except TemplateSyntaxError as e:
        raise TemplateError(f"Template error on line {e.lineno}: {e.message}") from None


def plain_text(html: str) -> str:
    """A readable text version of an HTML message (for the text part of an email and for previews)."""
    import re
    from html import unescape
    text = re.sub(r"(?is)<(script|style).*?</\1>", "", html or "")
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h[1-6]>|</li>", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", unescape(re.sub(r"<[^>]+>", "", text))).strip()


def render(src: str, ctx: dict, html: bool = False, limit: int = MAX_TEMPLATE, cap: int = MAX_OUTPUT) -> str:
    validate(src, limit)
    try:
        out = (HTML if html else TEXT).from_string(src or "").render(**ctx)
    except SecurityError:
        raise TemplateError("That template tries to do something that is not allowed") from None
    except TemplateSyntaxError as e:
        raise TemplateError(f"Template error on line {e.lineno}: {e.message}") from None
    except Exception as e:  # noqa: BLE001
        raise TemplateError(f"The template could not be rendered: {type(e).__name__}: {e}") from None
    return out[:cap]
