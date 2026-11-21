velora.listview_settings["Fixed Asset Revaluation"] = {
  add_fields: ["asset", "revaluation_date", "movement", "approval_status", "posting_batch"],
  get_indicator(doc) { return doc.docstatus === 1 ? ["Posted", "green"] : [doc.approval_status || "Pending", "orange"]; },
};
