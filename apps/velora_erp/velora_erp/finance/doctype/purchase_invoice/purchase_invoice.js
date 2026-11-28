velora.ui.form.on("Purchase Invoice", {
  refresh(frm) {
    frm.set_intro("Use the Is Fixed Asset flag on an invoice line to capitalise the acquisition directly into the Fixed Asset Register. The line must use the selected category's asset account. The supplier invoice remains the single source of the financial posting; asset records are created only after submission succeeds.");
    if (frm.doc.posting_batch) frm.add_button("View Posting Batch", () => { window.location.hash = `#/app/Financial Posting Batch/${encodeURIComponent(frm.doc.posting_batch)}`; });
  },
});
