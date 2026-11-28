frappe.listview_settings["Deferred Tax Posting Inbox"] = {
  onload(listview) {
    listview.page.add_inner_button("Pending Review", () => {
      listview.filter_area.clear();
      listview.filter_area.add(["Deferred Tax Posting Inbox", "status", "=", "Pending Review"]);
    });
  }
};
