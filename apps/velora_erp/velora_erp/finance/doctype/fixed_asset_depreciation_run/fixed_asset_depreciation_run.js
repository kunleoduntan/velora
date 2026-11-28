velora.ui.form.on("Fixed Asset Depreciation Run", {
  refresh(frm) {
    frm.set_intro("Build a controlled period depreciation run for active owned assets and right-of-use assets. Review calculated amounts and approve before posting. The run updates the asset subledger only after the central ledger posting succeeds.");
    if (frm.doc.posting_batch) frm.add_button("View Posting Batch", () => { window.location.hash = `#/app/Financial Posting Batch/${encodeURIComponent(frm.doc.posting_batch)}`; });
  },
});
