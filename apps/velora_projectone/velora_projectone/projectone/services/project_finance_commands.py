"""Governed native commands for project contracts and revenue recognition.

The host document engine owns persistence, permissions, transactions, workflow,
and audit. Financial source inputs are fetched from an injected host provider;
request bodies never supply authoritative actual costs or progress evidence.
"""
from __future__ import annotations

from copy import deepcopy

from .project_financial_control import (
    validate_performance_obligation, calculate_revenue_recognition,
)


class ProjectFinanceCommandService:
    def __init__(self, bridge, *, recognition_source_provider=None):
        self.bridge = bridge
        self.repository = bridge.document_repository()
        self.recognition_source_provider = recognition_source_provider

    def create_performance_obligation(self, actor, data, *, idempotency_key):
        self.bridge.assert_permission(actor, "projectone.performance_obligation.create",
                                      project_id=(data or {}).get("project"))
        payload = deepcopy(data or {})
        payload.pop("company", None)
        payload["status"] = "Draft"
        payload.setdefault("variable_consideration_constrained", True)
        validate_performance_obligation(payload)
        return self.repository.insert(actor, "Project Performance Obligation", payload,
                                      idempotency_key=idempotency_key)

    def workflow_action(self, actor, doctype, name, action, evidence=None):
        if doctype not in {"Project Performance Obligation", "Project Revenue Recognition"}:
            raise ValueError("Unsupported project finance workflow document.")
        return self.bridge.workflow_action(actor, doctype, name, action, evidence or {})

    def create_recognition_proposal(self, actor, *, obligation_name, period_end, idempotency_key):
        if self.recognition_source_provider is None:
            raise RuntimeError("Authoritative project finance source provider is not configured; caller-supplied cost/progress values are not accepted.")
        obligation = self.repository.get(actor, "Project Performance Obligation", obligation_name)
        if obligation is None:
            raise KeyError(obligation_name)
        if obligation.get("status") != "Approved":
            raise ValueError("Revenue recognition requires an approved performance obligation.")
        self.bridge.assert_permission(actor, "projectone.revenue_recognition.create",
                                      project_id=obligation.get("project"))
        provider = self.recognition_source_provider
        getter = getattr(provider, "get_recognition_inputs", None)
        if not callable(getter):
            raise RuntimeError("Project finance source provider must implement get_recognition_inputs().")
        source = getter(actor, obligation=deepcopy(obligation), period_end=period_end)
        if not isinstance(source, dict):
            raise TypeError("Project finance source provider returned an invalid payload.")
        if source.get("project") != obligation.get("project"):
            raise PermissionError("Financial source data must match the obligation project.")
        if source.get("currency") != obligation.get("currency"):
            raise ValueError("Financial source currency must match the approved performance obligation currency.")
        watermark = str(source.get("source_watermark") or "").strip()
        if not watermark:
            raise ValueError("Authoritative financial source watermark is required.")
        calculation_inputs = {
            "project": obligation["project"],
            "performance_obligation": obligation_name,
            "currency": obligation["currency"],
            "period_end": period_end,
            "transaction_price": obligation["allocated_transaction_price"],
            "method": obligation["recognition_method"],
            "recognition_over_time": obligation["recognition_over_time"],
            "variable_consideration_constrained": obligation.get("variable_consideration_constrained", True),
            "control_transfer_confirmed": bool(source.get("control_transfer_confirmed")),
            **{key: source[key] for key in (
                "cumulative_actual_cost", "forecast_total_cost", "prior_cumulative_revenue",
                "prior_cumulative_cost", "current_period_cost", "cumulative_output_units",
                "total_output_units", "achieved_milestone_value", "cumulative_progress_percent",
            ) if key in source},
        }
        proposal = calculate_revenue_recognition(**calculation_inputs)
        document = {
            "project": obligation["project"],
            "performance_obligation": obligation_name,
            "contract": obligation.get("contract_reference"),
            "period_end": period_end,
            "currency": obligation["currency"],
            "notes": "System-generated proposal; pending Finance review.",
        }
        computed = {
            "transaction_price": proposal["transaction_price"],
            "recognition_method": obligation["recognition_method"],
            "recognition_over_time": obligation["recognition_over_time"],
            "control_transfer_confirmed": bool(source.get("control_transfer_confirmed")),
            "progress_percent": proposal["progress_percent"],
            "cumulative_actual_cost": calculation_inputs["cumulative_actual_cost"],
            "forecast_total_cost": proposal["forecast_total_cost"],
            "prior_cumulative_revenue": proposal["prior_cumulative_revenue"],
            "cumulative_revenue": proposal["cumulative_revenue"],
            "current_period_revenue": proposal["current_period_revenue"],
            "cumulative_cost": proposal["cumulative_cost"],
            "current_period_cost": proposal["current_period_cost"],
            "cumulative_profit": proposal["cumulative_profit"],
            "current_period_profit": proposal["current_period_profit"],
            "forecast_total_profit": proposal["forecast_total_profit"],
            "forecast_margin_percent": proposal["forecast_margin_percent"],
            "potential_onerous_contract_loss": proposal["potential_onerous_contract_loss"],
            "source_watermark": watermark,
        }
        return self.repository.insert(actor, "Project Revenue Recognition", document,
                                      idempotency_key=idempotency_key,
                                      trusted_fields=computed)
