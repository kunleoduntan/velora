velora.listview_settings["Batch Bank Transaction"] = {
  add_fields: ["bank_account", "posting_date", "net_movement", "approval_status", "posting_batch"],
  get_indicator(doc) { return doc.docstatus === 1 ? ["Posted", "green"] : doc.approval_status === "Approved" ? ["Approved", "green"] : ["Pending Approval", "orange"]; },
};
