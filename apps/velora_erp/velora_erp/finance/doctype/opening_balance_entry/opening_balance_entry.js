velora.ui.form.on("Opening Balance Entry", {
  refresh(frm) {
    frm.set_intro("Opening balances are restricted to Asset, Liability and Equity accounts. The document requires independent approval and posts once to the Account Ledger.");
    frm.add_button("Trial Balance", () => { window.location.hash = "#/report/Trial Balance"; });
    frm.add_button("Account Ledger", () => { window.location.hash = "#/report/Account Ledger"; });
    if (frm.doc.docstatus === 1 && frm.doc.posting_batch) {
      frm.add_button("View Posting Batch", () => { window.location.hash = `#/app/Financial Posting Batch/${encodeURIComponent(frm.doc.posting_batch)}`; });
    }
  },
});
