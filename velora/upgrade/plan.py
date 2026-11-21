"""Reviewable, fingerprinted upgrade plans.

A plan file is a snapshot of the exact schema/patch work discovered for the selected
workspace targets. It is advisory and must be regenerated if code or database state changes.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .engine import UpgradeEngine
from .versions import code_version


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _fingerprint_payload(value: dict) -> bytes:
    stable = {k: v for k, v in value.items() if k not in {"fingerprint", "created_at"}}
    return _canonical(stable)


def build_plan(ws, only: list[str] | None = None) -> dict:
    targets = UpgradeEngine(ws, only=only).plan()
    body = {
        "format": "velora-upgrade-plan",
        "format_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "workspace": str(ws.root.resolve()),
        "code_version": code_version(),
        "selected_targets": only or [],
        "targets": targets,
        "safety": {
            "execution_requires_backup": True,
            "migration_preview_only": True,
            "live_database_changed": False,
        },
    }
    body["fingerprint"] = hashlib.sha256(_fingerprint_payload(body)).hexdigest()
    return body


def verify_plan_file(ws, path: str | Path, only: list[str] | None = None) -> dict:
    try:
        saved = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read upgrade plan: {exc}") from None
    if not isinstance(saved, dict) or saved.get("format") != "velora-upgrade-plan" or saved.get("format_version") != 1:
        raise ValueError("Unsupported upgrade plan file")
    fingerprint = saved.get("fingerprint")
    unsigned = {k: v for k, v in saved.items() if k != "fingerprint"}
    expected = hashlib.sha256(_fingerprint_payload(unsigned)).hexdigest()
    if not isinstance(fingerprint, str) or fingerprint != expected:
        raise ValueError("Upgrade plan fingerprint is invalid; the file may have been modified")
    current = build_plan(ws, only=only)
    if saved.get("workspace") != current["workspace"] or saved.get("code_version") != current["code_version"]:
        raise ValueError("Upgrade plan belongs to a different workspace or code version")
    if saved.get("selected_targets", []) != (only or []):
        raise ValueError("Upgrade target selection differs from the approved plan")
    if saved.get("fingerprint") != current["fingerprint"]:
        raise ValueError("The live migration plan has changed. Generate and review a fresh plan before upgrading.")
    return {"verified": True, "fingerprint": fingerprint, "targets": len(saved.get("targets", []))}
