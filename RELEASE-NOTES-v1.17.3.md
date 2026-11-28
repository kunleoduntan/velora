# Velora 1.17.3 (framework) with Governance 11.12.0

## Fixed
- Full-suite failures ("DocType 'Customer' does not exist"): two tests replaced a method on the registry proxy, which left a stale patched method behind for every later test. The proxy now refuses attribute patching and the two tests patch the Registry class instead. ERP Customer is unchanged and remains the base for the governance feed.

## Added (Governance 11.12.0)
- Recommended practices under each NCCG 2018 principle: 342 practices with the Code's reference numbers, in paraphrase. Assessments open with a practice row for each; a departure needs its explanation. Read the published Code for exact wording. Sector codes and SEC guidelines add practices not listed.
- SASB: SASB Industry, SASB Metric, SASB Adoption, SASB Metric Response. Nothing is pre-loaded because the content is licensed: download the Excel template, fill it from the standard you hold, import it. Responses fill from linked data points; omissions need a reason. The IFRS S2.32 checklist line reads these responses.
- Inline XBRL: Taxonomy Concept Map rows may take a figure from a data point (number, percentage, monetary) or narrative from a report section (text block). Units, scale and element names are entered by the preparer; none are supplied.
- Desk: IFRS S1/S2 readiness, Code assessment and SASB metrics tabs under Governance.

## Not done / limits
- Tests use SQLite only. The desk screens are unit-tested but not exercised in a browser.
- Inline XBRL is not validated against the taxonomy; validate with an XBRL processor before filing.
- No SASB content, taxonomy element names or ISSB industry guidance is included.
