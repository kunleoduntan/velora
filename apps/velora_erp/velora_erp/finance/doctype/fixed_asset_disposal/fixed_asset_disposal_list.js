velora.listview_settings["Fixed Asset Disposal"] = {
  add_fields: ["asset", "disposal_date", "carrying_amount", "gain_loss", "approval_status", "posting_batch"],
  get_indicator(doc) { return doc.docstatus === 1 ? ["Posted", "green"] : [doc.approval_status || "Pending", "orange"]; },
};
