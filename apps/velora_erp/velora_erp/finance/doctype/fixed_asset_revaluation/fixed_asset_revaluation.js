velora.ui.form.on("Fixed Asset Revaluation", {
  refresh(frm) {
    frm.set_intro("Revaluation uses carrying amount movement. Increases first reverse prior revaluation losses through income, then credit revaluation surplus; decreases first release existing surplus, then charge the residual loss to P&L.");
    if (frm.doc.posting_batch) frm.add_button("View Posting Batch", () => { window.location.hash = `#/app/Financial Posting Batch/${encodeURIComponent(frm.doc.posting_batch)}`; });
  },
});
