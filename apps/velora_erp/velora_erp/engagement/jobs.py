"""Scheduled entry point for Relationship Moments."""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def run_daily() -> dict:
    from . import service
    try:
        return service.run()
    except Exception:  # noqa: BLE001 - a kind word must never stop the other daily jobs
        log.exception("engagement daily run failed")
        return {}
