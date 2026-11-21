# Integrations (v0.12)

All integration credentials, subscriptions, queues and logs are stored in the **active company's database**. They are not shared with another company in the tenant or group.

## API credentials

A System Manager can create and revoke company-specific API credentials:

- `GET /api/integrations/api-keys`
- `POST /api/integrations/api-keys` with `{"label":"Payroll import","scopes":["read","write"],"expires_on":"2027-01-01T00:00:00"}`
- `DELETE /api/integrations/api-keys/{id}`

The raw key is returned once. Only its SHA-256 digest is stored. Supply it as `Authorization: Bearer vla_...` and include `X-Velora-Company: COMPANY-ID`. The API credential cannot switch companies. Its scope is checked for each request: safe HTTP methods require `read`, mutations require `write`, submit/cancel routes require `submit`, and report routes require `reports`.

The key's roles are `API Key` and `API:<scope>`. Grant those roles permissions on DocTypes only where required. API credentials do not inherit the creator's personal roles.

## SMS and WhatsApp provider adapters

No vendor is bundled because providers require external accounts, credentials and commercial agreements. An installed app registers an adapter:

```python
from velora.integration_engine import register_provider

def send_sms(recipient, message, config):
    # Call your provider SDK here; return its message/reference ID.
    return {"provider_id": "..."}

register_provider("SMS", send_sms)
```

Use `WHATSAPP` for a WhatsApp Business adapter. The provider implementation must load credentials from environment variables or a secret manager, never from source code or user-visible logs. `POST /api/integrations/messages` is restricted to System Manager.

## Outbound webhooks

- `GET /api/integrations/webhooks`
- `POST /api/integrations/webhooks` with `{"label":"Accounting bridge","target_url":"https://partner.example/webhooks/velora","events":["invoice.submitted"]}`
- `GET /api/integrations/logs`\n- `DELETE /api/integrations/webhooks/{id}` to deactivate a subscription\n- `POST /api/integrations/webhook-deliveries/{id}/retry` to retry a dead delivery

The webhook signing secret is returned once and encrypted in the company database using Fernet. Set `VELORA_INTEGRATION_MASTER_KEY` to a valid Fernet key and preserve it securely across deployments. It can be generated with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Outgoing requests include `X-Velora-Event`, `X-Velora-Delivery` and `X-Velora-Signature: sha256=<hex HMAC-SHA256>`. Verify the HMAC over the exact raw request body using the secret supplied at subscription creation. The worker revalidates HTTPS destinations and disallows redirects. Webhook delivery is at-least-once: consumers should deduplicate by `X-Velora-Delivery`.

An app can queue a business event after its transaction succeeds:

```python
from velora.integration_engine import enqueue_event
enqueue_event("invoice.submitted", {"doctype": "Sales Invoice", "name": "INV-0001"})
```

The `velora_notify` worker drains the queue when that app is installed. Outbound failures retry with bounded backoff and become visible in integration logs.

## Current boundaries

- SMS and WhatsApp are adapter interfaces; no provider is configured by default.
- Outbound webhooks are implemented; inbound webhook endpoints and OAuth2 client-credential grants are not included in this release.
- The API key system is company-local. Do not copy a key between companies.
- Protect the master key as a production secret and back it up separately from the database.
