# Velora Governance v1.9.0 — Governance Risk Intelligence

## Scope

Configurable weighted governance risk scoring, normalized factor inputs, weight validation, severity classification, risk register roll-up and high-priority risk counts. Weights and severity thresholds are configurable; no hardcoded approval or risk acceptance workflow.

## Configuration and governance safeguards

- Approval routing and approval authority are not hardcoded or duplicated.
- Automation services generate candidate actions only; dispatch, persistence, and approval remain native runtime integrations.
- Risk scoring is explainable by factor, value, weight and weighted contribution.
- Severity thresholds and factor weights can be overridden by configuration.

## Validation

tests: weighted score, thresholds, invalid factor/weight and register summary tests.

## Qualification

This release batch is unit-tested and source/package-validated. Native Velora installation, runtime permission filtering, scheduler execution, persistence, notification dispatch, browser UX and UAT remain to be qualified in the target runtime.
