"""Errors that help: every refusal carries what to do next.

A rule never weakens a control: the operation is still stopped when it must be (an unbalanced entry, a closed period, a missing permission).
What changes is the answer the person gets. Next to the message there is a plain `hint` (how to put it right), `actions` (links straight to
the screen that fixes it) and, where it applies, the `field` to correct. Things that are worth knowing but need not stop anyone are raised
with `warn()` instead: the work goes through and the person sees the note.

Apps add their own rules with the hook `error_advice`: a module (or list of modules) with RULES, each
{"pattern": regex, "hint": text, "actions": [{"label": ..., "href": ...}]}. Named groups of the pattern can be used in the hint and links
as {name}. A raise may also carry its own advice: throw(message, advice={...})."""
from __future__ import annotations

import re
from contextvars import ContextVar
from urllib.parse import quote

_warnings: ContextVar[list | None] = ContextVar("velora_warnings", default=None)


def _app(doctype: str, name: str = "") -> str:
    return f"#/app/{quote(doctype)}" + (f"/{quote(name)}" if name else "")


# Framework rules: they apply to every app.
FRAMEWORK_RULES = [
    {"kind": "MandatoryError", "pattern": r"^(?P<doctype>[^:]+): (?P<label>.+) needs at least one row$", "hint": "Add at least one row to {label}, then save again."},
    {"kind": "MandatoryError", "pattern": r"^(?P<doctype>[^:]+): (?P<label>.+) is required$", "hint": "Fill in {label}, then save again."},
    {"kind": "LinkValidationError", "pattern": r"^(?P<doctype>[^:]+): (?P<target>.+?) '(?P<value>[^']*)' does not exist", "hint": "Pick an existing {target} from the list, or create it first.",
     "actions": [{"label": "Create {target}", "href": "#/app/{target_q}/new"}]},
    {"kind": "PermissionDenied", "pattern": r"has no '(?P<perm>\w+)' permission on (?P<doctype>.+?)\.?$", "hint": "None of your roles may {perm} {doctype}. Ask a System Manager to add {perm} for one of your roles in Role Permissions, or to give you a role that has it.",
     "actions": [{"label": "Role Permissions", "href": "#/settings/permissions"}]},
    {"kind": "DuplicateEntryError", "pattern": r".", "hint": "A record with this name or key already exists. Open the existing one, or change the name and save again."},
    {"kind": "TimestampMismatchError", "pattern": r".", "hint": "Someone saved this document after you opened it. Reload it to see their changes, then make yours again."},
    {"kind": "DocStatusError", "pattern": r"cancel", "hint": "A cancelled document cannot change. Use Amend to make a corrected copy."},
    {"kind": "DocStatusError", "pattern": r"submit", "hint": "A submitted document cannot be edited. Cancel it, then Amend to correct it."},
    {"kind": "LinkedDocumentsError", "pattern": r".", "hint": "Other submitted documents depend on this one. Cancel those first (Cancel All lists them), then cancel this one."},
]


def _rules_from_apps() -> list[dict]:
    from importlib import import_module
    try:
        from .meta.registry import registry
        apps = list(registry.apps)
    except Exception:
        return []
    out = []
    for app_name in apps:
        try:
            hooks = import_module(f"{app_name}.hooks")
        except ModuleNotFoundError:
            continue
        paths = getattr(hooks, "error_advice", None)
        for path in ([paths] if isinstance(paths, str) else list(paths or [])):
            try:
                out.extend(import_module(path).RULES)
            except Exception:
                import logging
                logging.getLogger("velora.advice").warning("Error advice rules %s could not be loaded", path, exc_info=True)
    return out


def _fill(text: str, groups: dict) -> str:
    values = {**groups, **{f"{k}_q": quote(str(v)) for k, v in groups.items()}}
    try:
        return text.format(**values)
    except (KeyError, IndexError):
        return text


def advise(exc: BaseException) -> dict | None:
    """The advice for an error, or None. Explicit advice on the exception wins; then app rules; then framework rules."""
    own = getattr(exc, "advice", None)
    if own:
        return own
    message = str(exc)
    details = getattr(exc, "details", None) or {}
    for rule in _rules_from_apps() + FRAMEWORK_RULES:
        if rule.get("kind") and rule["kind"] not in {c.__name__ for c in type(exc).__mro__}:       # a rule for ValidationError also covers its kinds
            continue
        m = re.search(rule["pattern"], message)
        if not m:
            continue
        groups = {k: (v or "").strip() for k, v in m.groupdict().items()}
        out = {"hint": _fill(rule["hint"], groups), "actions": [{"label": _fill(a["label"], groups), "href": _fill(a["href"], groups)} for a in rule.get("actions", [])]}
        if isinstance(details, dict) and details.get("field"):
            out["field"] = details["field"]
        return out
    return None


def warn(message: str, *, hint: str = "", actions: list | None = None) -> None:
    """Tell the person something without stopping the work. Shown with the successful answer; never rolls anything back."""
    bucket = _warnings.get()
    note = {"message": str(message), "hint": hint, "actions": list(actions or [])}
    if bucket is None:
        import logging
        logging.getLogger("velora.advice").info("warning outside a request: %s", message)
        return
    if note not in bucket:
        bucket.append(note)


def collect():
    """Context manager used by the API: gathers the warnings raised while one request runs."""
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        token = _warnings.set([])
        try:
            yield _warnings.get()
        finally:
            _warnings.reset(token)
    return _ctx()
