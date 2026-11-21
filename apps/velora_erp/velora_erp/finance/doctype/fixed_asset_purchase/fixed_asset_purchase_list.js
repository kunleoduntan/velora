velora.listview_settings["Fixed Asset Purchase"] = {
  add_fields: ["purchase_date", "total_cost", "approval_status", "status"],
  get_indicator(doc) { return doc.status === "Posted" ? ["Posted", "green"] : ["Pending Approval", "orange"]; },
};
