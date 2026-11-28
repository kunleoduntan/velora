# Velora Governance and Sustainability: honest review (27 Nov 2026)

Scope of this review: the app as shipped (about 130 DocTypes, board, committees, resolutions, statutory registers, compliance, risk, policies, shareholders, sustainability metrics/targets/reports). I read the DocType definitions and the GHG, emission-factor, assurance, materiality and register structures and searched the code for named standards. I did not run it against a real client's data or a regulator's template, and I am not a substitute for a company secretary or a sustainability assurance provider.

## What is in good shape
- Board management is complete in structure: boards, committees and charters, agendas, attendance, minutes, resolutions with voting, board packs, evaluations, succession, skills matrix, conflicts of interest, director independence and training.
- Compliance and control: obligations, requirements, filings and submissions, evidence, exceptions with escalation, policies with acknowledgement and review, automation.
- Sustainability reporting has the right building blocks: frameworks, standards, topics, metrics, targets with progress, data collection tasks and quality, evidence, risks and opportunities, stakeholder engagement, report sections and content blocks, review issues, revisions, publication, assurance records.
- It now installs on the framework next to VeloraERP with no DocType name conflicts (integration test in the previous release).

## Gaps against the standards you would be measured on
These are things I could not find in the app. Some may be reachable by configuration; I list what I looked for.

1. **GHG accounting method.** `GHG Calculation` multiplies activity by one emission factor (kg CO2e per unit). Missing: separate **location-based and market-based Scope 2**; the **15 Scope 3 categories** as a structured list; **gas-by-gas** results (CO2, CH4, N2O, HFCs...) with a stated **GWP set (IPCC AR5/AR6)**; **biogenic emissions** reported separately; **base year and recalculation policy**; organisational boundary (equity share / financial control / operational control) and **intensity ratios**. The GHG Protocol is mentioned in text only.
2. **IFRS S1/S2 and ISSB.** Mentioned but no structured disclosure checklist by paragraph (governance, strategy, risk management, metrics and targets), no **climate scenario analysis**, no **transition plan**, no **industry-based metrics (SASB)** library, no **cross-industry metrics** set. For Nigeria this matters because the FRC roadmap adopts ISSB standards.
3. **Double materiality** exists as an assessment with impact and financial thresholds. Missing: stakeholder-weighted scoring workflow, value-chain scope, and a link from each material topic to the required disclosures (ESRS) so the report cannot omit one silently.
4. **Assurance.** `Sustainability Assurance` records provider, type and conclusion. Missing: limited vs reasonable assurance as a controlled choice, the standard used (ISAE 3000 / ISSA 5000), and **locking of a reporting period once assured**.
5. **Machine-readable output.** No **XBRL/iXBRL** tagging, which regulators and ISSB taxonomy filings increasingly expect. Reports are produced as documents.
6. **Nigerian specifics.** Nothing named for **CAMA 2020** statutory registers (members, directors, secretaries, charges, debenture holders, **persons with significant control**), **CAC annual returns** timelines, the **Nigerian Code of Corporate Governance 2018** principles or **SEC/NGX** disclosure rules. `Statutory Register Type` is a free list, so a company has to set these up itself; I did not find seeded definitions.
7. **Other frameworks** not found: TCFD (superseded but still referenced), TNFD (nature), CDP questionnaires, science-based targets, GRI is present.
8. **Data capture from the ERP.** Energy, fuel, travel, waste and procurement spend already sit in VeloraERP. There is no automatic feed from ERP purchases/stock into emission activity data; today activity data is typed in. This is the biggest practical gain still on the table (spend-based and activity-based Scope 3 from purchase invoices).
9. **Board e-voting and signatures** exist at record level; I did not verify legal-grade signature capture or quorum enforcement against each board type's rules.

## Recommendation (order of value)
1. Restructure `GHG Calculation` (scope/category, gas-by-gas, GWP set, location vs market) and add the ERP activity feed.
2. Seed CAMA 2020 registers and NCCG 2018 principle checklist.
3. IFRS S1/S2 disclosure checklist tied to material topics.
4. Assurance controls and period locking.
5. iXBRL export last, once the data model above is stable.

## Status after Governance 11.10.0
Done: item 1 in part (gas-by-gas, GWP set, location/market Scope 2, Scope 3 categories, biogenic, boundary, base year, inventory roll-up; **not** the ERP activity feed), item 4 (assurance standard, level, opinion, period locking), item 6 in part (NCCG 2018 principle checklist, more register types; **not** seeded section references or practices).
Still open: items 2, 3 (partly), 5, 7, 8 and the remainder of 1 and 6.

## Status after Governance 11.11.0
Done in this release: ERP-to-emissions spend feed (item 1 remainder), IFRS S1/S2 requirement checklist with evidence from the system (item 2), structured double materiality with approval (item 3), climate scenario analysis (S2.22), S2.33/36 target detail, and an Inline XBRL engine.
Not done: taxonomy element names for iXBRL (must be entered from the taxonomy release), SASB industry metrics, narrative facts in iXBRL.
