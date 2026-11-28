velora.listview_settings["Fixed Asset"] = {
  add_fields: ["asset_category", "company", "acquisition_date", "carrying_amount", "status"],
  get_indicator(doc) { return doc.status === "Disposed" ? ["Disposed", "grey"] : doc.status === "Leased" ? ["Leased", "blue"] : ["Active", "green"]; },
};
