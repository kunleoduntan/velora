import pytest
from velora.notification_delivery import DeliveryError, deliver_alerts, send_webhook

def test_no_alerts_does_not_send():
    assert deliver_alerts({"alerts": []}) == {"sent": 0, "results": []}

def test_webhook_requires_https():
    with pytest.raises(DeliveryError): send_webhook("http://example.com/hook", {})

def test_webhook_rejects_embedded_credentials():
    with pytest.raises(DeliveryError): send_webhook("https://user:pass@example.com/hook", {})

def test_delivery_is_opt_in():
    assert deliver_alerts({"alerts":[{"code":"disk","message":"low"}]}) == {"sent":0,"results":[]}
