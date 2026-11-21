frappe.ui.form.on("Deferred Tax Posting Inbox", {
  refresh(frm) {
    if (frm.doc.posting_batch) {
      frm.add_button("View Posting Batch", () => {
        window.location.hash = `#/app/Financial Posting Batch/${encodeURIComponent(frm.doc.posting_batch)}`;
      });
    }
    if (frm.doc.source_assessment) {
      frm.add_button("View Assessment", () => {
        window.location.hash = `#/app/Deferred Tax Assessment/${encodeURIComponent(frm.doc.source_assessment)}`;
      });
    }
  }
});
