velora.ui.form.on("Fixed Asset Purchase", {
  refresh(frm) {
    frm.set_intro("Use Purchase Invoice for normal supplier invoice matching. This document is for controlled direct asset acquisition and creates Fixed Asset register records after its financial posting succeeds.");
    if (frm.doc.created_assets) frm.add_button("Open Fixed Asset Register", () => { window.location.hash = "#/app/Fixed Asset"; });
  },
});
