velora.ui.form.on("Fixed Asset Disposal", {
  refresh(frm) {
    frm.set_intro("Disposal clears gross asset cost, accumulated depreciation and impairment, records proceeds and posts the resulting gain or loss. Posted disposals are corrected by controlled reversal and reinstatement.");
    if (frm.doc.posting_batch) frm.add_button("View Posting Batch", () => { window.location.hash = `#/app/Financial Posting Batch/${encodeURIComponent(frm.doc.posting_batch)}`; });
  },
});
