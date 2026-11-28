"""Preference-aware notification planning and delivery adapter."""
CHANNELS = {"in_app", "email", "sms", "push"}

def plan_notifications(events, *, recipients=None, preferences=None, templates=None):
    recipients = recipients or {}
    preferences = preferences or {}
    templates = templates or {}
    plans = []
    for event in events or []:
        event = dict(event or {})
        event_type = event.get("event_type")
        template = templates.get(event_type, {})
        for user in event.get("recipient_ids", []):
            user_pref = preferences.get(user, {})
            channels = user_pref.get("channels", ["in_app"])
            if user_pref.get("disabled", False):
                continue
            for channel in channels:
                if channel not in CHANNELS:
                    continue
                if channel not in template.get("channels", channels):
                    continue
                plans.append({"event_id": event.get("event_id"), "event_type": event_type,
                    "recipient_id": user, "channel": channel,
                    "template_key": template.get("template_key", event_type),
                    "payload": event.get("payload", {}), "idempotency_key": f"{event.get('event_id')}:{user}:{channel}"})
    return plans

def dispatch_notifications(plans, *, dispatchers=None, delivery_recorder=None, existing_keys=None, dry_run=True):
    dispatchers = dispatchers or {}
    existing = set(existing_keys or [])
    outcomes = []
    for plan in plans or []:
        key = plan.get("idempotency_key")
        channel = plan.get("channel")
        if not key:
            outcomes.append({"status": "rejected", "reason": "missing_idempotency_key"}); continue
        if key in existing:
            outcomes.append({"status": "duplicate_suppressed", "idempotency_key": key}); continue
        fn = dispatchers.get(channel)
        if not callable(fn):
            outcomes.append({"status": "adapter_unavailable", "channel": channel, "idempotency_key": key}); continue
        if dry_run:
            outcomes.append({"status": "validated", "idempotency_key": key, "channel": channel}); continue
        try:
            result = fn(plan)
            status = "delivered"
        except Exception as exc:
            result = {"error": str(exc), "error_type": type(exc).__name__}
            status = "failed"
        if callable(delivery_recorder):
            try:
                delivery_recorder(plan, status, result)
            except Exception as exc:
                status = "recording_failed"
                result = dict(result or {}, recording_error=str(exc))
        outcomes.append({"status": status, "idempotency_key": key, "channel": channel, "result": result})
        if status == "delivered": existing.add(key)
    return {"total": len(plans or []), "outcomes": outcomes,
            "delivered": sum(o.get("status") == "delivered" for o in outcomes),
            "failed": sum(o.get("status") in {"failed", "recording_failed"} for o in outcomes)}
