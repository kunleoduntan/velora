velora.listview_settings["Fixed Asset Lease"] = {
  add_fields: ["lease_start_date", "lease_end_date", "present_value", "status"],
  get_indicator(doc) { return doc.status === "Active" ? ["Active", "green"] : [doc.status || "Draft", "orange"]; },
};
