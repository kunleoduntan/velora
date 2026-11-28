# VeloraERP 2.100.0 with framework 1.17.5: Withholding tax, company income tax and the Tax Centre

## What you can now do

**Withholding tax (Tax Journal).** One document, one table. Each row is a Customer or a Supplier.
- Customer row: the customer paid you net of tax and gave you a certificate. Posts Dr WHT credit account (asset) / Cr customer.
- Supplier row: you paid the supplier net of tax and must remit it. Posts Dr supplier / Cr WHT payable account (liability).
- A row that names an invoice settles that invoice by the tax amount; your receipt or payment settles the net. Together they close the invoice. Cancelling the journal reopens it.
- The rate comes from an approved WHT Tax Rule, or you type the certificate amount. The account must be the right side (asset for customers, liability for suppliers).
- Approval is through your workflow, as everywhere. No journal is created from outside the GUI.
- Tax Settings can require the customer's certificate number before submit.

**Investments, dividends and everything else.** Tax Journal rows can also be *Income received* (tax withheld at source from your dividends, interest, rent or royalties: a credit) and *Payment made* (tax you withheld from dividends, interest, rent, fees paid to people who are not suppliers: payable). Each row carries the nature of payment, whether the other party is corporate, an individual, or federal, state or local government, and a counter account (for example dividend income, or dividends payable). Rates come from separate approved WHT rules, so individual and corporate rates differ by rule.

**Federal and state.** Tax Jurisdiction now has a level (Federal, State, Local). Federal and state taxes are separate jurisdictions with their own rules, obligations and returns.

**Deadlines, exposure, reminders.** Tax Settings holds the WHT remittance day and VAT filing day (of the following month) taken from the law in force; the daily job then creates the monthly obligations from the ledger. Enter the late penalty, monthly penalty % and annual interest % to see an estimated exposure on overdue items (Tax Centre and adviser). Reminders go out through your notification rules for the events `tax_obligation_due_soon` and `tax_obligation_overdue`; you must create those rules in notification settings, otherwise nothing is sent.

**Company income tax (Income Tax Computation).**
- Account now has Tax treatment: Allowable, Not tax allowed, Partly allowable (with %), Capital (use capital allowance), Exempt income.
- "Calculate" reads profit from the ledger for the period, adds back flagged expenses, deducts exempt income, takes your manual lines (deductions, capital allowances, other), relieves losses brought forward (proposed from your last approved computation), applies the approved Income Tax rule (flat or tiered), compares with minimum tax on turnover if you set one, adds levies, and subtracts withholding tax credits (up to the tax charged).
- Submitting is refused if the ledger moved after you calculated.

**Tax Centre.** Position (VAT, WHT payable and credits, deadlines), the Tax Adviser's findings, VAT by month, and shortcuts to every tax document, setting and report. Also reachable from the Tax Management hub.

**Tax Adviser.** Deterministic checks: missing approved rules, rules without a tax account, overdue and due-soon filings, tax posted under codes with no rule, customer WHT without certificates, unused WHT credits, expense accounts whose names suggest a tax decision (fines, donations, depreciation, provisions...) still marked Allowable, no computation for last year. Two AI advisors are registered for free-form questions: Tax Adviser and Income Tax Computation Reviewer. They explain and review; they cannot post or change anything.

**New reports:** WHT Register, WHT Position by Party, Income Tax Computation Summary, Tax Treatment of Accounts. The catalogue now maps 29 of its 460 entries to executable reports.

## Where every withholding tax line comes from (the design)
One ledger, many sources, one report. Any document that posts a line to a WHT account carrying an approved WHT rule code reaches the tax ledger. **WHT All Sources** lists them all with the document each came from, split into credits suffered and tax payable, with totals per source.
- *Customer withholds on a receipt:* on the Receipt, add a line debiting the WHT credit account with the WHT rule code and tax amount (the customer line carries the gross). Or record it later, when the certificate arrives, in a Tax Journal. Both reach the same report.
- *We withhold on a payment:* the same on the Payment (credit WHT payable), or a Tax Journal.
- *Investments:* set the WHT rule code in Finance Settings > Investments; tax withheld on interest, dividends and rent is then tagged and appears in the report as Investment income.
- *Dividends:* use a Tax Journal row (Income received for dividends you receive, Payment made for dividends you pay, nature = Dividend). A dedicated dividend declaration document with a shareholder table is **not built**; I did not want a second place that posts the same tax.

## Print formats
Receipt Voucher, Official Receipt (customer-facing, with amount in words, invoices settled and a withholding tax note) and Payment Voucher (with signature blocks). Open Tax Centre and press "Install sample print formats"; then choose them when printing a Receipt or Payment. Replace YOUR ORGANISATION NAME and the address at the top of each. The Receipt and Official Receipt render was tested; the Payment Voucher passed template validation but its render was not tested. Amount in words now works in every print format (naira/kobo, dollars/cents and a few other currencies).

## Honest limits
- No statutory rate is built in. Enter the current rates (VAT, each WHT category, the company income tax rate, levies, minimum tax) as Tax Rules and approve them. Check them against the law in force.
- Capital allowances are entered as lines. There is no asset-by-asset allowance engine yet. Balancing charges, group relief, transfer pricing, thin capitalisation and similar rules are not computed.
- The adviser's expense-name check is a prompt to review, not a conclusion.
- Penalty and interest are estimates from the rates you enter, not an assessment. Reminders need notification rules to exist; I could not test delivery.
- Tested on SQLite only; not clicked through in a browser.
- 431 of the 460 catalogue reports are still specifications only.
- Payroll tax is untouched.
