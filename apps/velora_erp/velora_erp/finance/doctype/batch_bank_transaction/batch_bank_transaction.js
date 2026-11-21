velora.ui.form.on("Batch Bank Transaction", {
  refresh(frm) {
    frm.set_intro("One bank account per batch. Receipts debit the bank and credit the offset account; payments debit the offset account and credit the bank. Submission posts all lines atomically through the Financial Posting Engine.");
    if (frm.doc.posting_batch) frm.add_button("View Posting Batch", () => { window.location.hash = `#/app/Financial Posting Batch/${encodeURIComponent(frm.doc.posting_batch)}`; });
  },
});
