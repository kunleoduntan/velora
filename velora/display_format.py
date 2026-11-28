"""How dates and numbers are shown in this company: one setting that every list, report and form follows."""
from fastapi import Body, Request

from .exceptions import PermissionDenied, ValidationError
from .permissions import get_session
from .settings import get_setting, set_setting

KEY = "display.format"
DATES = {"YYYY-MM-DD": "2026-12-31", "DD/MM/YYYY": "31/12/2026", "MM/DD/YYYY": "12/31/2026", "DD-MMM-YYYY": "31-Dec-2026", "DD MMM YYYY": "31 Dec 2026"}
NUMBERS = {"1,234.56": "1,234.56", "1.234,56": "1.234,56", "1 234,56": "1 234,56", "1'234.56": "1'234.56"}
DEFAULT = {"date": "YYYY-MM-DD", "number": "1,234.56"}


def current() -> dict:
    saved = get_setting(KEY) or {}
    return {"date": saved.get("date") if saved.get("date") in DATES else DEFAULT["date"],
            "number": saved.get("number") if saved.get("number") in NUMBERS else DEFAULT["number"]}


def save(data: dict) -> dict:
    s = get_session()
    if s.user != "Administrator" and "System Manager" not in s.roles:
        raise PermissionDenied("Only a System Manager can change how dates and numbers are shown")
    date, number = str(data.get("date") or ""), str(data.get("number") or "")
    if date not in DATES or number not in NUMBERS:
        raise ValidationError("Choose one of the listed date and number formats")
    set_setting(KEY, {"date": date, "number": number})
    return current()


def options() -> dict:
    return {"dates": [{"value": k, "example": v} for k, v in DATES.items()], "numbers": [{"value": k, "example": v} for k, v in NUMBERS.items()]}


def install_routes(app, run):
    @app.get("/api/display-format")
    def display_format(request: Request):
        return run(request, lambda: {**current(), **options()})

    @app.put("/api/display-format")
    def display_format_save(request: Request, body: dict = Body(...)):
        return run(request, lambda: {**save(body), **options()})
