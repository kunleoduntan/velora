velora.ui.form.on("Bank Transaction Processor", {
  refresh(frm) {
    frm.set_intro("Import or paste bank statement lines, apply deterministic coding rules, resolve exceptions, then submit to create a separate approval-controlled Bank Batch. No ledger posting occurs from this processor.");
    if (frm.doc.generated_batch) frm.add_button("Open Bank Batch", () => { window.location.hash = `#/app/Batch Bank Transaction/${encodeURIComponent(frm.doc.generated_batch)}`; });
  },
});
