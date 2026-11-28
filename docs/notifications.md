# Notifications (`velora_notify`, bundled with the framework)

Install on a company or site: `velora --company COMP-001 install-app velora_notify` (it ships inside Velora; no `apps/` folder needed). Run the worker next to the server: **`velora worker`**.

## What it does
A **rule** says: *when* something happens to a DocType (New, Save, Value Change, Submit, Cancel, N days before/after a date field, or a Custom event your code triggers), *if* a condition holds, *tell whom*, *through which channels*, with *what message*.

| | |
|---|---|
| **Channels** | In-App (the bell + inbox), Email (SMTP), signed Webhook; SMS/WhatsApp/Slack/... by registering a sender: `velora_notify.channels.register("SMS", send)` |
| **Recipients** | a field holding a user/email (several allowed), everyone with a **role** in the company, a fixed user or email, or an **expression** (`doc.owner_email`). The person who made the change is excluded by default |
| **Conditions** | a safe expression language: `doc.status == "Approved" and doc.grand_total > 1000000`, `changed("status")`, `transition("status","Draft","Approved")`, `days_until(doc.due_date) <= 3`, `has_role("Auditor")` |
| **Messages** | sandboxed templates: `Invoice {{ doc.name }} for {{ doc.grand_total\|money }} is due {{ doc.due_date\|date }}` - a missing value prints nothing, never "None" |
| **Priority** | Low / Normal / High / Urgent. Urgent ignores quiet hours and digests |
| **Per person** | turn email off, **quiet hours** (may cross midnight), **hourly/daily digest** (one combined email), **mute** a rule |
| **Throttle** | "do not repeat within N minutes", per recipient |
| **Escalation** | if a rule's in-app notification is still **unread after N minutes**, pass it (once) to a role or user |
| **Preview** | `POST /api/notification-rules/preview` shows who would be told what, for a real document, without sending anything |

## Why it is reliable
* **Written with the document.** Notifications are created in the *same transaction* as the change, inside a savepoint: none is lost when the document commits, none exists for a document that rolled back, and **a broken rule can never make a save fail** (it is recorded under `notify.errors`).
* **Exactly once.** Every notification has an idempotency key (rule + document + version + recipient + channel): replaying an event, a retried request or a second scan adds nothing.
* **Outbox with retries.** Email/webhook deliveries are queued and sent by the worker *outside* any database transaction, each outcome committed on its own. A failure backs off 1 min → 5 min → 30 min → 2 h → 12 h, then becomes **Dead** (visible; an administrator can retry it). A permanent error (bad address, rejected by the receiver, not configured) is Dead at once. A worker that dies mid-send leaves a row that is recovered after 10 minutes. Several workers share the queue safely (atomic claim; proven on PostgreSQL).
* **Safe by construction.** Conditions and templates come from administrators' text: conditions run in a small interpreter (not `eval`: no imports, no attribute tricks, no calls except a fixed list, length and node limits); templates run in Jinja's sandbox. Email headers can't be injected; webhooks must be https and **cannot target private/internal addresses** (unless explicitly allowed); each webhook carries an HMAC signature the receiver can verify.
* **Private.** You only ever see your own notifications (someone else's looks like a missing one); the raw log and outbox are administrator-only.

## Setup
Email and webhooks are configured in `notify.settings` (API: `PUT /api/notification-settings`, administrators only). **Secrets are never stored there**: you give the *name of an environment variable*.
```json
{"email": {"host": "smtp.example.com", "port": 587, "user": "mailer", "password_env": "SMTP_PASSWORD", "from_addr": "noreply@example.com", "starttls": true},
 "webhook": {"secret_env": "NOTIFY_WEBHOOK_SECRET"}, "base_url": "https://erp.example.com"}
```
`POST /api/notification-settings/test-email` sends a test message. `base_url` makes links in emails absolute.

## From your own code
```python
from velora_notify import trigger
trigger("Payment Failed", doc, key="attempt-3")     # fires Custom rules named "Payment Failed"; the same key twice is a no-op
```

## Honest limits
* **No SMS/WhatsApp adapter ships** (they need a provider account); the channel interface is there. Email was tested against a fake SMTP server and webhooks against a real local HTTP server; **I have not sent through a real mail provider** - use the test-email button first.
* Quiet hours, daily digests (08:00) and "N days before" use the **server's clock/time zone**, not each person's.
* The bell is **live** (see `postgresql.md`, section 5) and falls back to polling every 30 s (every 2 minutes while connected, as a safety net) if the stream cannot connect.
* The SMTP password can only come from an environment variable (no encrypted-in-the-database entry yet).
* A rule on a *child table* is not possible (attach it to the parent). Attachments/PDFs and approve-by-link buttons are not built yet.
* If the process dies between a successful send and the commit, that one message may be sent twice (at-least-once delivery).
