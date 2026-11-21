velora.ui.form.on("Support Ticket", {
  refresh(frm) {
    const d = frm.doc;
    if (frm.is_new()) { frm.set_intro("Describe the request. The service level, team and agent are chosen when you save."); return; }
    const addLine = (kind, status) => () => {
      frm.add_table_row("replies", { kind, message: "" });
      if (status) frm.set_value("status", status);
      velora.msgprint("A new line was added under Conversation. Write the message there, then save.", "info");
    };
    if (!["Resolved", "Closed"].includes(d.status)) {
      frm.add_button("Reply to customer", addLine("Reply to customer", d.status === "Open" ? "In Progress" : undefined));
      frm.add_button("Add internal note", addLine("Internal note"));
      frm.add_button("Wait on customer", () => frm.set_value("status", "Waiting on Customer"));
      frm.add_button("Mark resolved", () => frm.set_value("status", "Resolved"));
    } else {
      frm.add_button("Reopen", () => frm.set_value("status", "Open"));
    }
    frm.add_button("Support Desk", () => { window.location.hash = "#/support"; });
    if (d.response_sla === "Breached" || d.resolution_sla === "Breached") frm.set_intro("This ticket has breached its service level.");
    else if (d.response_sla === "At risk" || d.resolution_sla === "At risk") frm.set_intro("This ticket is close to breaching its service level.");
  },
});
