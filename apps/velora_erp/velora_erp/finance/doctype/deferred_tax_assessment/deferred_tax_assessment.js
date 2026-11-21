frappe.ui.form.on("Deferred Tax Assessment", {
  refresh(frm) {
    if (frm.doc.posting_inbox) {
      frm.add_button("Open Deferred Tax Posting Inbox", () => {
        window.location.hash = `#/app/Deferred Tax Posting Inbox/${encodeURIComponent(frm.doc.posting_inbox)}`;
      });
    }
  }
});
