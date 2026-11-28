# Velora Governance 11.11.0

Second tranche of the standards review.

## ERP-to-emissions activity feed
- **Spend Emission Rule**: maps an expense account, item group, item or supplier to an Emission Source and a spend-based Emission Factor (or marks spend as deliberately excluded, with a reason). First match by priority, then specificity. A rule with no matcher is refused.
- **Preview and run** (`preview_activity_feed`, `run_activity_feed`): reads submitted, non-rejected Purchase Invoices dated within the Sustainability Reporting Period, in the books' base currency, and writes one GHG Calculation per rule. Re-running recomputes the period, so it refreshes rather than adds; calculations no longer supported are removed. Hand-entered calculations are never touched, and an overlap on the same source is warned about.
- **Coverage is reported**: estimated, excluded and unmapped spend, with the unmapped accounts listed. Unmapped spend is not in the inventory.
- Refused when a completed assurance has locked the period.
- Spend-based figures are the lowest-quality method in the GHG Protocol hierarchy. A purchase return or debit note is not netted (the Purchase Invoice has no return flag).

## IFRS S1 / S2
- 82 requirement rows at paragraph level (S2 governance, strategy 10-22, risk management 25, metrics 29(a)-(g), 32-36; S1 governance, strategy, risk, metrics and general requirements), seeded as Sustainability Disclosures. Paragraph numbers were checked against the standards; the wording is a paraphrase.
- `generate_issb_checklist` opens one Sustainability Disclosure Assessment per requirement for a reporting period. `get_issb_readiness` reads readiness by pillar, taking evidence from the GHG inventory, climate targets, scenario analysis and materiality. A requirement marked complete with no supporting data is reported as an inconsistency. `can_state_compliance` is true only when nothing is open.
- Notes surface the December 2025 S2 amendments (effective 1 January 2027) and warn when the default GWP set is not AR6.
- **Sustainability Target** carries the S2.33/36 detail (objective, coverage, gases, scopes, gross or net, carbon credits, validation, revisions); a non-draft climate target without it is refused.

## Double materiality
- **Materiality Assessment** scores impact (scale, scope, irremediable character, likelihood; a potential human-rights impact is judged on severity) and financial materiality (magnitude x likelihood) from structured criteria. A topic is material if either is. Overrides need a reason; completing needs stakeholder engagement, a rationale for each non-material topic, and board or committee approval. `apply_materiality_to_disclosures` sets Disclosure Applicability from a completed assessment.
- The scoring rules are the entity's method, not a prescribed one; state them in the report.

## Climate scenario analysis
- **Climate Scenario Analysis** (scenarios, assumptions, effects by horizon, uncertainties, capacity to adjust). Completing needs what IFRS S2 paragraph 22 asks to be disclosed.

## Inline XBRL export
- `export_ixbrl` builds a well-formed Inline XBRL document (header, context, unit, nonFraction facts) for Scope 1, Scope 2 (location and market) and Scope 3 from the GHG inventory.
- **The taxonomy element names, namespace, entry-point URL and unit measure are NOT supplied.** Enter them in XBRL Export Setting and Taxonomy Concept Map from the taxonomy release you file against. Facts without an element name are listed, not exported.
- The output has not been validated against the taxonomy. Validate with an XBRL processor and the regulator's rules before filing.

## Still open
SASB industry metrics; the remaining ISSB facts (S2 narratives, assets exposed, capital deployed, targets) in iXBRL; Scope 3 category facts in iXBRL; netting of returns in the activity feed; the recommended practices under each NCCG principle; section references for each statutory register; a screen for the code assessment and the checklist beyond the generic forms.
