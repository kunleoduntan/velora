from velora import Document, throw

from velora_erp.support import service as svc

ONE_WAY = {"Closed": ("Open",)}          # a closed ticket can only be reopened, never moved to the middle states


class SupportTicket(Document):
    def validate(self):
        now = svc.utcnow()
        old = self._old or {}
        prior = old.get("status")
        settings = svc.get_settings()
        fresh = not old
        if fresh:
            self.opened_on = now
            if not self.priority:
                self.priority = settings["default_priority"]
        if prior == "Closed" and self.status not in ("Closed", "Open"):
            throw("A closed ticket can only be reopened.")
        if self.requester_type == "Customer" and not self.customer and not fresh:
            throw("Choose the customer.")
        if self.satisfaction not in (None, "") and not 1 <= int(self.satisfaction) <= 5:
            throw("Satisfaction is a score from 1 to 5.")
        self._stamp_replies(now)
        # who is it for, and which clocks apply
        if fresh or any(old.get(f) != getattr(self, f) for f in ("priority", "customer", "category")):
            svc.stamp_due_dates(self, now)
        # status movement
        if self.status != prior:
            self._on_status_change(prior, now)
        # automatic assignment
        if not self.team:
            self.team = svc.resolve_team(self, settings)
        if self.team and not self.assigned_to:
            self.assigned_to = svc.pick_agent(self.team)
        svc.refresh_states(self, now=now)

    def _stamp_replies(self, now):
        for row in self.replies or []:
            if row.posted_on:
                continue
            row.posted_on = now
            customer_side = row.kind == "Customer reply"
            row.author = (self.requester_name or self.customer or "Customer") if customer_side else svc.current_user()
            if row.kind == "Reply to customer" and not self.first_responded_on:
                self.first_responded_on = now
            if customer_side and self.status in ("Waiting on Customer", "Resolved", "Closed"):
                self.status = "Open"

    def _on_status_change(self, prior, now):
        if prior == "Waiting on Customer" and self.paused_since:
            svc.shift_for_pause(self, self.paused_since, now)
            self.paused_since = None
        if self.status == "Waiting on Customer":
            self.paused_since = now
        if self.status == "Resolved":
            self.resolved_on = now
        if self.status == "Closed":
            self.closed_on = now
            if not self.resolved_on:
                self.resolved_on = now
        if prior in ("Resolved", "Closed") and self.status in ("Open", "In Progress", "Waiting on Customer"):
            self.reopen_count = int(self.reopen_count or 0) + 1
            self.resolved_on = None
            self.closed_on = None
