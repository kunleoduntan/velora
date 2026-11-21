velora.ui.form.on("Accrual", {
  refresh(frm) {
    frm.set_intro("Period-end accruals are posted through the central ledger. When automatic reversal is enabled, a scheduled process reverses the original posting on the selected date.");
    if (frm.doc.posting_batch) frm.add_button("View Posting Batch", () => { window.location.hash = `#/app/Financial Posting Batch/${encodeURIComponent(frm.doc.posting_batch)}`; });
    if (frm.doc.reversal_batch) frm.add_button("View Reversal", () => { window.location.hash = `#/app/Financial Posting Batch/${encodeURIComponent(frm.doc.reversal_batch)}`; });
  },
});
