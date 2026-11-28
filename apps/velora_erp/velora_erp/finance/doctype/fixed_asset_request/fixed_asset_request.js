velora.ui.form.on("Fixed Asset Request", {
  refresh(frm) {
    frm.set_intro("Capital expenditure requests are approval-controlled and do not affect the ledger. An approved request can be referenced by a Fixed Asset Purchase.");
    if (frm.doc.converted_purchase) frm.add_button("Open Purchase", () => { window.location.hash = `#/app/Fixed Asset Purchase/${encodeURIComponent(frm.doc.converted_purchase)}`; });
  },
});
