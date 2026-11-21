velora.ui.form.on("Financial Voucher", {
  refresh(frm) {
    frm.set_intro("Controlled manual adjustment. The voucher is posted through the central Financial Posting Engine; submitted entries are corrected by reversal, never by editing the ledger.");
    frm.add_button("Account Ledger", () => { window.location.hash = "#/report/Account Ledger"; });
    frm.add_button("Financial Statements", () => { window.location.hash = "#/financial-reports"; });
    if (frm.doc.docstatus === 1 && frm.doc.posting_batch) {
      frm.add_button("View Posting Batch", () => { window.location.hash = `#/app/Financial Posting Batch/${encodeURIComponent(frm.doc.posting_batch)}`; });
    }
  },
  posting_date(frm) {
    frm.set_intro("Posting Date determines the Financial Year and Financial Period. The posting engine will reject dates in closed periods.");
  },
});
