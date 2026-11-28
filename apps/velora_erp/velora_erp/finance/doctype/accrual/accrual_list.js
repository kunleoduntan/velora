velora.listview_settings["Accrual"] = {
  add_fields: ["reporting_date", "total_accrual", "approval_status", "status", "posting_batch"],
  get_indicator(doc) { return doc.status === "Reversed" ? ["Reversed", "blue"] : doc.status === "Posted" ? ["Posted", "green"] : ["Pending Approval", "orange"]; },
};
