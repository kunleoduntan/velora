from datetime import datetime, timezone
import pytest
from velora import activity
from velora.permissions import Session, session_as
from velora.exceptions import ValidationError

def test_activity_event_redacts_sensitive_fields(site):
    with session_as(Session("auditor", frozenset({"System Manager"}))):
        result=activity.record_event("updated","Supplier updated",doctype="Supplier",document_name="SUP-1",
          changed_fields=["supplier_name","email_id","api_secret","credit_limit"],summary="Supplier details changed",
          source="api",metadata={"region":"West","api_token":"never"})
        assert result["id"]
        data=activity.feed(limit=10)
        item=next(x for x in data["items"] if x["id"]==result["id"])
        assert item["changed_fields"]==["supplier_name","credit_limit"]
        assert item["summary"]=="Supplier details changed"
        assert item["actor"]=="auditor"

def test_activity_rejects_unknown_event_type(site):
    with session_as(Session("auditor", frozenset({"System Manager"}))):
        with pytest.raises(ValidationError):
            activity.record_event("made_up","Invalid event")

def test_activity_subscriptions_are_user_scoped(site):
    with session_as(Session("alice", frozenset({"System Manager"}))):
        activity.save_subscriptions([{"event_type":"submitted","doctype":"Sales Invoice","enabled":True}])
        assert len(activity.my_subscriptions())==1
    with session_as(Session("bob", frozenset({"System Manager"}))):
        assert activity.my_subscriptions()==[]
