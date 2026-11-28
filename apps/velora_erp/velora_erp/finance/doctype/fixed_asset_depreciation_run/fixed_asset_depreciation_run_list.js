velora.listview_settings["Fixed Asset Depreciation Run"] = {
  add_fields: ["company", "period_end", "total_depreciation", "approval_status"],
  get_indicator(doc) {
    if (doc.docstatus === 1) return ["Posted", "green", "docstatus,=,1"];
    if (doc.approval_status === "Approved") return ["Approved", "blue", "approval_status,=,Approved"];
    if (doc.approval_status === "Rejected") return ["Rejected", "red", "approval_status,=,Rejected"];
    return ["Pending", "orange", "approval_status,=,Pending"];
  },
};
