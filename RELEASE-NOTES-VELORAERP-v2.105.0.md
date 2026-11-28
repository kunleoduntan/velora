# VeloraERP 2.105.0: full review, findings fixed

Requires Velora >=1.18.0,<1.20.0.

## Findings and fixes
1. Critical: foreign-currency documents with several lines were refused because each line rounds separately (proved: 3 USD invoices out of 3). The cent difference now posts to the new Finance Settings field Exchange Rounding Account (or the realised exchange gain/loss account). A larger difference is still refused. Tests: test_posting_rounding.py.
2. Actions from a Fixed Asset: Revalue, Dispose, Impairment Test, Transfer, Adjust Component. Each opens the action document pre-filled and unsaved. Tests: test_asset_actions.py.
3. IAS 16: disposal and revaluation refused until depreciation is posted to the end of the previous month.
4. Velora Admin Service Feedback had no permissions; now readable by System Manager and Administration Manager.
5. Locale: attendance time zones no longer default to Africa/Lagos; SLA offset defaults to UTC; examples no longer assume NGN.
6. Create From was six stacked versions of one function; now one routing table.
7. 23 deprecated utcnow calls replaced.
8. Four silent error handlers now log (approval policy, workflow templates, frozen workflow definitions, attendance shift lookup).
9. Out-of-date disposal message about leased assets corrected.

## Left as is, on purpose
- Setup still falls back to NG/NGN when VELORA_COUNTRY / VELORA_BASE_CURRENCY are not set (existing installations and the test suite rely on it).
- Payroll statutory fields (for example NHF) untouched, as instructed.
- Both "Administration Manager" and "Administrative Manager" stay accepted in Velora Admin (existing users hold either).
- Governance calls its host adapter `frappe` (a working shim, 235 calls; renaming is cosmetic).
