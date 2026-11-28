"""No hardcoded HR workflow templates are installed by VeloraERP.

HR teams configure each DocType's workflow in the shared Workflow Designer.
This compatibility module returns an empty catalogue for older integrations.
"""
from __future__ import annotations


def templates() -> list[dict]:
    return []


def install_templates(doctypes: list[str] | None = None, enabled: bool = False, system: bool = False) -> dict:
    return {"created": [], "skipped": []}
