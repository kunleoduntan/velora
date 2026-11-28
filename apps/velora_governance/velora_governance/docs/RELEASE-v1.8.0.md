# Velora Governance v1.8.0 — Governance Automation & Intelligent Operations

## Scope

Configuration-driven reminder and escalation candidate engine, notification message templates, configurable reminder windows, overdue escalation thresholds, terminal status exclusions and prioritised action candidates. Automation evaluation remains a pure service: it produces candidates and does not send notifications or trigger approval decisions.

## Configuration and governance safeguards

- Approval routing and approval authority are not hardcoded or duplicated.
- Automation services generate candidate actions only; dispatch, persistence, and approval remain native runtime integrations.
- Risk scoring is explainable by factor, value, weight and weighted contribution.
- Severity thresholds and factor weights can be overridden by configuration.

## Validation

tests: governance automation unit tests; due-date boundary and configurable rules tested.

## Qualification

This release batch is unit-tested and source/package-validated. Native Velora installation, runtime permission filtering, scheduler execution, persistence, notification dispatch, browser UX and UAT remain to be qualified in the target runtime.
