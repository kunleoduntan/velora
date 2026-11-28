"""Scheduled tasks (see hooks.py). `deliver` runs every worker tick and commits after every send."""
from . import engine, outbox


def deliver():
    outbox.process_due()


deliver.manages_transactions = True           # the scheduler must not wrap it in ONE transaction: each send is committed on its own


def maintain():
    outbox.recover_stuck()
    outbox.release_digests()
    engine.escalate()


def scan_dates():
    engine.scan_date_rules()


def deliver_integrations():
    """Drain the framework's signed outbound webhook queue."""
    from velora.integration_engine import deliver_webhooks
    deliver_webhooks()


deliver_integrations.manages_transactions = True


def maintain_integrations():
    from velora.integration_engine import recover_stuck_webhooks
    recover_stuck_webhooks()
