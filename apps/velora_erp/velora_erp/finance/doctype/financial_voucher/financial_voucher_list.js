velora.listview_settings["Financial Voucher"] = {
  add_fields: ["posting_date", "purpose", "approval_status", "total_debit", "total_credit", "posting_batch"],
  get_indicator(doc) {
    if (doc.docstatus === 1) return ["Posted", "green"];
    if (doc.approval_status === "Rejected") return ["Rejected", "red"];
    if (doc.approval_status === "Approved") return ["Approved · Ready to Post", "green"];
    return ["Pending Approval", "orange"];
  },
};
