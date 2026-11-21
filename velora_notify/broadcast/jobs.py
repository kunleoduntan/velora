"""Scheduled Broadcast Centre work (every minute): start broadcasts whose time has come and keep the results of running ones up to date."""
from __future__ import annotations

from velora import get_list
from velora.document.document import now

from . import service


def run_scheduled() -> int:
    started = 0
    for row in get_list("Broadcast", filters=[["status", "=", "Scheduled"], ["scheduled_for", "<=", now()]], fields=["name"], limit=200, ignore_permissions=True):
        try:
            service.send(row["name"])
            started += 1
        except Exception:  # noqa: BLE001 - one broadcast's problem must not stop the others
            pass
    return started


def sync_running() -> int:
    n = 0
    for row in get_list("Broadcast", filters={"status": "Sending"}, fields=["name"], limit=200, ignore_permissions=True):
        try:
            service.sync(row["name"])
            n += 1
        except Exception:  # noqa: BLE001
            pass
    return n


def tick() -> dict:
    return {"started": run_scheduled(), "synced": sync_running()}
