velora.ui.form.on("Broadcast", {
  refresh(frm) {
    const d = frm.doc;
    const base = `/api/broadcasts/${encodeURIComponent(d.name)}`;
    const call = (label, url, body, say) => frm.add_button(label, async () => {
      try { const r = await velora.api("POST", url, body); velora.msgprint(say(r), "green"); velora.reload(); }
      catch (e) { velora.msgprint(e.message || String(e), "red"); }
    });
    if (frm.is_new()) { frm.set_intro("Write the message, choose who receives it, then save. You can send a test before the real send."); return; }
    if (["Draft", "Scheduled"].includes(d.status)) {
      call("Build recipients", `${base}/build`, {}, r => `${r.will_send} will receive it; ${r.skipped} skipped; ${r.opted_out} opted out.`);
      frm.add_button("Send a test", async () => {
        const to = (d.test_to || "").trim();
        if (!to) { velora.msgprint("Type an address or number in 'Send a test to' (Results tab), save, then try again.", "red"); return; }
        try { const r = await velora.api("POST", `${base}/test`, { to }); velora.msgprint(r.sent ? `Test sent to ${to}.` : `Could not send: ${r.error}`, r.sent ? "green" : "red"); }
        catch (e) { velora.msgprint(e.message || String(e), "red"); }
      });
      call(d.scheduled_for ? "Schedule" : "Send now", `${base}/send`, d.scheduled_for ? { send_at: d.scheduled_for } : {}, r => r.status === "Scheduled" ? `Scheduled for ${r.scheduled_for}.` : `Queued for ${r.queued} people.`);
    }
    if (["Scheduled", "Sending"].includes(d.status)) call("Cancel sending", `${base}/cancel`, {}, r => `${r.stopped} waiting messages were stopped.`);
    if (["Sending", "Sent", "Partly Sent"].includes(d.status)) call("Refresh results", `${base}/sync`, {}, r => `${r.sent} sent, ${r.failed} failed, ${r.waiting} waiting.`);
    frm.add_button("Preview", async () => {
      try { const r = await velora.api("GET", `${base}/preview`); velora.msgprint(`To ${r.recipient}: ${r.subject ? r.subject + " — " : ""}${r.body.slice(0, 300)}`, "info"); }
      catch (e) { velora.msgprint(e.message || String(e), "red"); }
    });
    frm.add_button("Broadcast Centre", () => { window.location.hash = "#/broadcasts"; });
  },
});
