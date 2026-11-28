"""Company-local file storage and attachment regression tests."""
import hashlib
import pytest

from velora import new_doc, db
from velora.files import add_attachment, list_attachments, get_file, delete_attachment
from velora.permissions import Session, session_as
from velora.exceptions import PermissionDenied


def test_attachment_is_company_local_and_integrity_checked(site, tmp_path, monkeypatch):
    monkeypatch.setenv("VELORA_FILE_ROOT", str(tmp_path / "company-files"))
    customer = new_doc("Customer", customer_name="Attachment Customer").insert()
    payload = b"Velora attachment payload"
    record = add_attachment(payload, "invoice scan.pdf", doctype="Customer", docname=customer.name,
                            content_type="application/pdf", description="Supporting invoice")
    assert record["file_name"] == "invoice scan.pdf"
    assert record["sha256"] == hashlib.sha256(payload).hexdigest()
    assert len(list_attachments("Customer", customer.name)) == 1
    metadata, downloaded = get_file(record["id"])
    assert downloaded == payload
    assert metadata["attached_name"] == customer.name


def test_attachment_download_obeys_document_permission(site, tmp_path, monkeypatch):
    monkeypatch.setenv("VELORA_FILE_ROOT", str(tmp_path / "company-files"))
    customer = new_doc("Customer", customer_name="Private Attachment Customer").insert()
    record = add_attachment(b"private", "private.txt", doctype="Customer", docname=customer.name)
    with session_as(Session("reader@example.com", frozenset())):
        with pytest.raises(PermissionDenied):
            get_file(record["id"])


def test_attachment_delete_removes_metadata_and_binary(site, tmp_path, monkeypatch):
    monkeypatch.setenv("VELORA_FILE_ROOT", str(tmp_path / "company-files"))
    customer = new_doc("Customer", customer_name="Delete Attachment Customer").insert()
    record = add_attachment(b"remove-me", "remove.txt", doctype="Customer", docname=customer.name)
    delete_attachment(record["id"])
    with pytest.raises(Exception, match="File not found"):
        get_file(record["id"])


def test_attachment_rejects_oversized_payload(site, tmp_path, monkeypatch):
    monkeypatch.setenv("VELORA_FILE_ROOT", str(tmp_path / "company-files"))
    customer = new_doc("Customer", customer_name="Large Attachment Customer").insert()
    from velora.files import MAX_FILE_BYTES
    with pytest.raises(Exception, match="exceeds"):
        add_attachment(b"x" * (MAX_FILE_BYTES + 1), "large.bin", doctype="Customer", docname=customer.name)


def test_attachment_staging_is_cleaned_when_outer_transaction_rolls_back(site, tmp_path, monkeypatch):
    monkeypatch.setenv("VELORA_FILE_ROOT", str(tmp_path / "rollback-files"))
    customer = new_doc("Customer", customer_name="Rollback Attachment Customer").insert()
    from velora.files import storage_root
    with pytest.raises(RuntimeError, match="rollback"):
        with db.transaction():
            add_attachment(b"temporary", "temporary.txt", doctype="Customer", docname=customer.name)
            raise RuntimeError("rollback")
    root = storage_root()
    assert not list(root.rglob("*.pending-*"))


def test_attachment_http_api_upload_list_and_download(site, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from velora.api import create_app
    monkeypatch.setenv("VELORA_FILE_ROOT", str(tmp_path / "http-files"))
    customer = new_doc("Customer", customer_name="HTTP Attachment Customer").insert()
    client = TestClient(create_app(auto_init=False))
    headers = {"X-Velora-User": "Administrator", "Content-Type": "application/octet-stream", "X-Filename": "http.txt"}
    uploaded = client.post(f"/api/files?doctype=Customer&docname={customer.name}", headers=headers, content=b"hello over HTTP")
    assert uploaded.status_code == 200, uploaded.text
    file_id = uploaded.json()["data"]["id"]
    listed = client.get(f"/api/files?doctype=Customer&docname={customer.name}", headers={"X-Velora-User":"Administrator"})
    assert listed.status_code == 200 and len(listed.json()["data"]) == 1
    downloaded = client.get(f"/api/files/{file_id}", headers={"X-Velora-User":"Administrator"})
    assert downloaded.status_code == 200 and downloaded.content == b"hello over HTTP"


def test_configured_storage_root_still_separates_companies(site, tmp_path, monkeypatch):
    from velora.company import CompanyInfo, company_context
    monkeypatch.setenv("VELORA_FILE_ROOT", str(tmp_path / "shared-root"))
    from velora.files import storage_root
    with company_context(CompanyInfo("COMP-A", "Company A", "TENANT", "Tenant", None)):
        first = storage_root()
    with company_context(CompanyInfo("COMP-B", "Company B", "TENANT", "Tenant", None)):
        second = storage_root()
    assert first != second
    assert first.name == "COMP-A" and second.name == "COMP-B"
