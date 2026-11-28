"""Named default values: a field whose default is ``@name`` takes its starting value from the ``default_providers`` hook of an installed app.

An app declares ``default_providers = {"base_currency": "my_app.module.function"}`` in its hooks.py; the function takes no arguments and returns the value
(or None). This lets a form start in the company's own currency instead of a country baked into the field definition.
"""
from __future__ import annotations

import importlib

from .meta.registry import registry


def resolve(token: str):
    name = token[1:]
    for app in getattr(registry, "_apps", []):
        try:
            hooks = importlib.import_module(f"{app}.hooks")
        except ModuleNotFoundError as exc:
            if exc.name == f"{app}.hooks":
                continue
            raise
        path = (getattr(hooks, "default_providers", None) or {}).get(name)
        if path:
            module, _, func = path.rpartition(".")
            try:
                return getattr(importlib.import_module(module), func)()
            except Exception:  # noqa: BLE001 - a default must never stop a form from opening
                return None
    return None
