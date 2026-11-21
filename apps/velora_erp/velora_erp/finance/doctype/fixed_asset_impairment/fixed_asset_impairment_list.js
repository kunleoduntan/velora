velora.listview_settings["Fixed Asset Impairment"] = {
  add_fields: ["company", "asset", "assessment_date", "action", "impairment_movement", "approval_status"],
  get_indicator(doc) { if (doc.docstatus === 1) return ["Posted", "green", "docstatus,=,1"]; return [doc.approval_status || "Pending", doc.approval_status === "Approved" ? "blue" : "orange", `approval_status,=,${doc.approval_status || "Pending"}`]; },
};
