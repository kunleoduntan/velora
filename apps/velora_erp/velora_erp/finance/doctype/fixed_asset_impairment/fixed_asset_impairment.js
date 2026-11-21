velora.ui.form.on("Fixed Asset Impairment", {
  refresh(frm) {
    frm.set_intro("Recognise an impairment loss when recoverable amount is below carrying amount. A reversal is capped at the carrying amount that would have existed had the impairment never been recognised. Evidence and independent approval are required.");
    frm.toggle_display("impairment_expense_account", frm.doc.action === "Recognise Impairment");
    frm.toggle_display("impairment_reversal_account", frm.doc.action === "Reverse Impairment");
    if (frm.doc.posting_batch) frm.add_button("View Posting Batch", () => { window.location.hash = `#/app/Financial Posting Batch/${encodeURIComponent(frm.doc.posting_batch)}`; });
  },
  action(frm) { frm.trigger("refresh"); },
});
