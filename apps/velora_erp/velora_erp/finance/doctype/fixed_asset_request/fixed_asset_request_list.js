velora.listview_settings["Fixed Asset Request"] = {
  add_fields: ["request_date", "estimated_total", "approval_status", "status"],
  get_indicator(doc) { return doc.status === "Converted" ? ["Converted", "green"] : doc.approval_status === "Approved" ? ["Approved", "green"] : doc.approval_status === "Rejected" ? ["Rejected", "red"] : ["Pending", "orange"]; },
};
