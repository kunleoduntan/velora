# VeloraERP 2.104.0: module audit and standardisation

Goal: Velora is a global suite, not a Nigerian one. This release audits the finance modules against international standards (IFRS) and fixes what the audit found.

## Fixed
- Realised exchange differences (IAS 21.28): a foreign invoice settled at another rate now clears at its booked rate and the difference is posted to the realised gain or loss account (Finance Settings). Before, the receivable or payable was cleared at the settlement rate and left a residue.
- Hard-coded currency: the base currency is no longer assumed anywhere in code. Defaults come from the installation (environment variables at install time). Treasury wording uses the base currency.

## New
- Foreign Currency Revaluation (IAS 21.23): restates foreign receivables, payables, bank and cash, loans and accruals to the closing rate; posts the unrealised gain or loss per currency; optional automatic reversal; a missing rate stops the document instead of guessing; submitting re-checks the ledger.
- Expected Credit Loss Assessment (IFRS 9 simplified approach): provision matrix by ageing bucket; posts only the change in the allowance (charge or release).
- Provision Entry (IAS 37): recognise, increase, unwind discount, utilise, release; recognition criteria must be confirmed; cannot use or release more than the provision holds.
- Account types Loss Allowance and Provision.
- Six sample approval workflows, offered in the starter list and installed switched off only on request (named SAMPLE (off) - ...), for documents that move stock or money. Nothing is hard-coded: each company draws, changes and switches on its own.
- Posting engine: a batch whose lines are all exchange differences may have base amounts only (revaluation).

## Audit result: not built yet
- Inventory net realisable value (IAS 2): Stock Revaluation can write stock down and up, but there is no guided NRV assessment.
- Write-off of a receivable against the allowance as its own document (Party Adjustment covers write-offs today).
- Credit notes and returns are not netted in the ECL exposure (open invoices only).
- Install-time wizard for country and currency (environment variables for now).
- Payroll statutory components were left untouched on request.

## Tests (SQLite only)
See the manual section "What is verified, and what is not" for the run results.
