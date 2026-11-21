# VeloraERP v0.5.0 — Customer and Supplier Foundations

## Delivered

- Customer and Customer Group masters.
- Supplier and Supplier Group masters.
- Reusable Payment Terms with due-date and early-settlement discount validation.
- Default receivables/payables control account validation.
- Customer credit limit and credit hold master fields.
- Party existence, active status, party type and account financial-class validation in the central Financial Posting Engine.
- Customer Statement and Supplier Statement reports sourced from Account Ledger Records.
- Party balances by account and control-account reconciliation utilities.
- Finance workspace shortcuts for customers, suppliers, groups, payment terms and statements.
- Native Velora metadata-driven Desk integration; no separate frontend.

## Architecture

Account Ledger Records remain the only financial source of truth. Customer/Supplier balances and statements are read models. The source-adapter contract and central Financial Posting Engine remain the only supported route for creating ledger records.

## Not included

Sales/Purchase invoices, receipts, payments, allocation, credit-limit enforcement during transactions, ageing and dunning are deferred to subsequent releases.

## Dependency

Velora Framework `>=0.83,<0.84`.
