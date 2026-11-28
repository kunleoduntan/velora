# Velora Governance 11.10.0

First tranche of the standards review (see GOVERNANCE-SUSTAINABILITY-REVIEW.md in the package root).

## GHG accounting (GHG Protocol)
- **Gas-by-gas conversion with a stated GWP set.** New `GWP Set` (IPCC AR5 and AR6 100-year, seeded and editable) and gas rows on `Emission Factor`. A factor is either combined (kg CO2e) or gas-by-gas, never both (it would double count). A missing GWP is an error, not a silent zero. Each calculation stores its gas breakdown and GWP set.
- **Scope 2 location-based and market-based.** A Scope 2 calculation must say which; a factor labelled one way cannot be used as the other.
- **Scope 3 by the 15 categories.** A Scope 3 source must have a category.
- **Biogenic CO2** is recorded and reported separately, never added to the total.
- **`GHG Inventory Setting`:** organisational boundary (operational control / financial control / equity share), default GWP set, base year, base-year emissions, recalculation threshold.
- **Inventory roll-up** (`get_ghg_inventory`): Scope 1, Scope 2 both ways, Scope 3 by category, totals location- and market-based, by gas, intensity, change against the base year, and warnings (missing method/category, mixed GWP sets, no boundary stated).

## Assurance
- A completed assurance must state the level (limited/reasonable), provider, **standard** (ISAE 3000 (Revised), ISSA 5000, ISAE 3410, AA1000AS), **opinion** and reporting period.
- **A completed assurance locks that entity-period's GHG Calculations and Data Points** (no create, edit, move or delete). A Governance Administrator can release the lock with a written reason; who and when are stamped and kept in the history.
- Existing completed assurance records must be completed with the new fields the next time they are saved.

## Codes and registers
- **Nigerian Code of Corporate Governance 2018:** the six parts and 28 principle titles (from the published Code) are seeded as a `Governance Code`. `Code Compliance Assessment` starts with one response per principle and demands an explanation for anything not fully applied (apply-and-explain), with application percentage.
- **Statutory register types** added: persons with significant control, debenture holders, directors' interests in shares and debentures, minutes of general and board meetings.

## Not done (still open)
IFRS S1/S2 disclosure checklist and scenario analysis, SASB industry metrics, XBRL/iXBRL export, ERP-to-emissions activity feed, the recommended practices under each NCCG principle, section references for each register (confirm with counsel).
