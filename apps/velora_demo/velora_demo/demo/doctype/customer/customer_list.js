velora.listview_settings["Customer"] = {
  add_fields: ["status"],
  get_indicator(doc) {
    if (doc.status === "Active") return ["Active", "green"];
    if (doc.status === "Blocked") return ["Blocked", "red"];
    return ["Inactive", "grey"];
  },
};
