velora.ui.form.on("Fixed Asset Lease", {
  refresh(frm) {
    frm.set_intro("This release supports lessee-side IFRS 16 initial recognition, discounted lease payment schedules and controlled instalment settlement through Payment → Lease Payment. Lessor accounting and lease termination are separate capabilities.");
    if (frm.doc.right_of_use_asset) frm.add_button("Open Right-of-Use Asset", () => { window.location.hash = `#/app/Fixed Asset/${encodeURIComponent(frm.doc.right_of_use_asset)}`; });
    if (frm.doc.posting_batch) frm.add_button("View Commencement Posting", () => { window.location.hash = `#/app/Financial Posting Batch/${encodeURIComponent(frm.doc.posting_batch)}`; });
  },
});
