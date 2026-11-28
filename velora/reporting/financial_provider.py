"""Financial reporting adapter discovery.

Installed accounting applications may expose their authoritative ledger through a
small provider contract declared in their hooks.py. This keeps the report designer
and financial statement renderer independent of any one ERP's DocType schema.
"""
from __future__ import annotations

import importlib
from ..exceptions import ValidationError
from ..meta.registry import registry


def resolve_financial_reporting_provider():
    providers = []
    for app_name in registry.apps:
        try:
            hooks = importlib.import_module(f"{app_name}.hooks")
        except ModuleNotFoundError as exc:
            if exc.name == f"{app_name}.hooks":
                continue
            raise
        target = getattr(hooks, "financial_reporting_provider", None)
        if not target:
            continue
        if not isinstance(target, str) or "." not in target:
            raise ValidationError(f"{app_name}.hooks.financial_reporting_provider must be a dotted module path")
        providers.append((app_name, importlib.import_module(target)))
    if len(providers) > 1:
        names = ", ".join(name for name, _ in providers)
        raise ValidationError(f"Multiple financial reporting providers are installed ({names}). Only one authoritative ledger provider is permitted.")
    return providers[0][1] if providers else None
