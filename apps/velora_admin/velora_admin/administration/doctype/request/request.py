from datetime import datetime, timedelta

from velora import Document, get_doc, get_list, throw


class Request(Document):
    """Administrative request lifecycle and approval-chain preparation."""

    def before_validate(self):
        if self.request_type:
            try:
                request_type = get_doc("Request Type", self.request_type)
                if request_type and request_type.is_active:
                    if not self.department and request_type.default_department:
                        self.department = request_type.default_department
                    if not self.approval_matrix and request_type.default_approval_matrix:
                        self.approval_matrix = request_type.default_approval_matrix
            except Exception:
                # Link validation remains the framework's responsibility; do not mask
                # the user's ability to correct a missing/inactive request type.
                pass

    def validate(self):
        if self.estimated_cost is not None and float(self.estimated_cost) < 0:
            throw("Estimated Cost cannot be negative.")
        if self.required_by_date and self.description and len(self.description.strip()) < 5:
            throw("Please provide a meaningful request description.")
        if self.status not in (None, "Draft", "Pending Approval", "Approved", "Rejected", "In Progress", "Completed", "Cancelled"):
            throw("Invalid Request status.")
        if self.current_level is not None and int(self.current_level) < 0:
            throw("Current Approval Level cannot be negative.")

    def before_submit(self):
        if not (self.description or "").strip():
            throw("Description is required before submitting an Request.")
        if not self.approval_matrix:
            throw("An Approval Matrix must be selected before submitting this request.")
        matrix = get_doc("Approval Matrix", self.approval_matrix)
        if not matrix or not matrix.is_active:
            throw("The selected Approval Matrix is missing or inactive.")
        if not matrix.levels:
            throw("The selected Approval Matrix has no approval levels.")

        amount = float(self.estimated_cost or 0)
        eligible = []
        for level in matrix.levels:
            minimum = float(level.min_amount or 0)
            maximum = float(level.max_amount or 0)
            if amount >= minimum and (maximum <= 0 or amount <= maximum):
                eligible.append(level)
        eligible.sort(key=lambda row: int(row.level_no or 0))
        if not eligible:
            throw("No approval levels in the selected matrix apply to this request amount.")

        history = []
        from velora_admin.administration.approval_service import _resolve_dynamic_approver
        for level in eligible:
            approver_type = level.approver_type or ""
            if approver_type == "Specific Role":
                assigned = level.approver_role
                if not assigned:
                    throw(f"Approval level {level.level_no} requires an Approver Role.")
            elif approver_type == "Specific User":
                assigned = level.approver_user
                if not assigned:
                    throw(f"Approval level {level.level_no} requires an Approver User.")
            elif approver_type in ("Requester's Manager", "Department Head"):
                assigned = _resolve_dynamic_approver(self, approver_type)
            else:
                throw(f"Unsupported approver type on level {level.level_no}.")
            history.append({
                "level_no": int(level.level_no or 0),
                "approver_type": approver_type,
                "assigned_approver": assigned,
                "status": "Pending" if not history else "Waiting",
            })
        self.set("approval_history", history)
        self.current_level = int(eligible[0].level_no or 0)
        self.status = "Pending Approval"
        if not self.sla_due_datetime:
            sla_hours = 48
            try:
                rules = get_list("Approval Escalation Rule", filters={"scope": "Request", "is_active": 1}, fields=["sla_hours"], limit=1, ignore_permissions=True)
                if rules and int(rules[0].get("sla_hours") or 0) > 0:
                    sla_hours = int(rules[0]["sla_hours"])
            except Exception:
                pass
            self.sla_due_datetime = (datetime.now() + timedelta(hours=sla_hours)).strftime("%Y-%m-%d %H:%M:%S")
        self.sla_status = "On Track"

    def on_submit(self):
        self.status = "Pending Approval"

    def before_cancel(self):
        if self.status in ("Completed", "Rejected"):
            throw(f"A {self.status.lower()} request cannot be cancelled.")

    def on_cancel(self):
        self.status = "Cancelled"
