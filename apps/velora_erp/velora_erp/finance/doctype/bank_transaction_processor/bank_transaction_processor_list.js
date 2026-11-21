velora.listview_settings["Bank Transaction Processor"] = {
  add_fields: ["bank_account", "statement_date_to", "total_receipts", "total_payments", "exception_count", "status"],
  get_indicator(doc) { return doc.status === "Batch Created" ? ["Batch Created", "green"] : doc.exception_count ? ["Needs Coding", "orange"] : ["Draft", "blue"]; },
};
