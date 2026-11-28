velora.listview_settings["Opening Balance Entry"] = {
  add_fields: ["opening_date", "migration_reference", "approval_status", "total_debit", "total_credit", "posting_batch"],
  get_indicator(doc) {
    if (doc.docstatus === 1) return ["Posted", "green"];
    if (doc.approval_status === "Rejected") return ["Rejected", "red"];
    if (doc.approval_status === "Approved") return ["Approved · Ready to Post", "green"];
    return ["Pending Approval", "orange"];
  },
};
