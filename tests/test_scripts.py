"""Company-local custom Server Script and Client Script regression tests."""
import pytest
from fastapi.testclient import TestClient
from velora import new_doc
from velora.api import create_app
from velora.permissions import Session, session_as
from velora.exceptions import PermissionDenied, ValidationError
from velora import db
from velora.scripts import save_script, list_scripts, client_code


def test_client_script_is_company_local_and_served_to_form(site):
    save_script({'script_type':'client','name':'Customer Form UX','doctype':'Customer','event':'form',
        'code':'velora.ui.form.on("Customer", { refresh(frm) { frm.set_intro("Company A custom form"); } });','enabled':True})
    assert 'Company A custom form' in client_code('Customer','form')
    assert client_code('Customer','list') == ''
    assert list_scripts('client','Customer')[0]['version'] == 1


def test_client_script_crud_api_requires_system_manager(site):
    client=TestClient(create_app(auto_init=False))
    admin={'X-Velora-User':'Administrator','X-Velora-Roles':'System Manager'}
    response=client.post('/api/custom-scripts',headers=admin,json={'script_type':'client','name':'Customer List UX',
        'doctype':'Customer','event':'list','code':'velora.listview_settings["Customer"] = {};','enabled':True})
    assert response.status_code==200, response.text
    assert response.json()['data']['version']==1
    reader={'X-Velora-User':'reader@example.com'}
    denied=client.get('/api/custom-scripts',headers=reader)
    assert denied.status_code==403


def test_server_script_validation_and_execution_use_pure_python(site):
    result = save_script({'script_type':'server','name':'Reject Negative Total','doctype':'Customer','event':'validate',
        'code':'if doc.credit_limit < 0:\n    throw("Credit limit cannot be negative")'})
    assert result['version'] == 1
    from velora.scripts import _run_server_script
    doc = new_doc('Customer', customer_name='Negative Credit', credit_limit=-10)
    row = {'name':'Reject Negative Credit','code':'if doc.credit_limit < 0:\n    throw("Credit limit cannot be negative")'}
    with pytest.raises(ValidationError, match='Credit limit cannot be negative'):
        _run_server_script(row, doc)


def test_server_script_rejects_imports_and_arbitrary_attribute_access(site):
    from velora.scripts import validate_script
    with pytest.raises(ValidationError, match='Unsafe Server Script'):
        validate_script({'script_type':'server','name':'Bad Import','doctype':'Customer','event':'validate','code':'import os'})
    with pytest.raises(ValidationError, match='Unsafe Server Script'):
        validate_script({'script_type':'server','name':'Bad Attribute','doctype':'Customer','event':'validate','code':'x = doc.__class__'})


def test_script_validation_rejects_unknown_doctype_and_event(site):
    with pytest.raises(Exception):
        save_script({'script_type':'client','name':'Bad','doctype':'Unknown DocType','event':'form','code':'// x'})
    with pytest.raises(ValidationError,match='Unsupported'):
        save_script({'script_type':'client','name':'Bad Event','doctype':'Customer','event':'before_insert','code':'// x'})



def test_client_typescript_source_and_revision_history(site):
    first = save_script({'script_type':'client','language':'typescript','name':'TS Form','doctype':'Customer','event':'form',
        'code':'velora.ui.form.on("Customer", { refresh(frm) { frm.set_intro("TS"); } });',
        'source_code':'const greeting: string = "TS"; velora.ui.form.on("Customer", { refresh(frm) { frm.set_intro(greeting); } });'})
    second = save_script({'script_type':'client','language':'typescript','name':'TS Form','doctype':'Customer','event':'form',
        'code':'velora.ui.form.on("Customer", { refresh(frm) { frm.set_intro("TS v2"); } });',
        'source_code':'const greeting: string = "TS v2"; velora.ui.form.on("Customer", { refresh(frm) { frm.set_intro(greeting); } });'})
    from velora.scripts import script_history, restore_script
    history = script_history(first['id'])
    assert [x['version'] for x in history] == [2, 1]
    restored = restore_script(first['id'], 1)
    assert restored['version'] == 3
    assert 'TS' in restored['source_code']


def test_v18_script_table_is_upgraded_additively(tmp_path):
    from sqlalchemy import create_engine, inspect
    from velora.scripts import ensure
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE vl_custom_script (id VARCHAR(32) PRIMARY KEY, script_type VARCHAR(16) NOT NULL, name VARCHAR(140) NOT NULL, doctype VARCHAR(140) NOT NULL, event VARCHAR(40) NOT NULL, code TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, version INTEGER NOT NULL DEFAULT 1, created_by VARCHAR(254), modified_by VARCHAR(254), created_on DATETIME, modified_on DATETIME, CONSTRAINT uq_vl_custom_script_type_name UNIQUE (script_type, name))")
        conn.exec_driver_sql("INSERT INTO vl_custom_script (id,script_type,name,doctype,event,code) VALUES ('old1','client','Old Client','Customer','form','// old')")
    ensure(engine)
    cols = {c['name'] for c in inspect(engine).get_columns('vl_custom_script')}
    assert {'source_code','language'} <= cols
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT language FROM vl_custom_script WHERE id='old1'").scalar_one() == 'javascript'
        assert inspect(conn).has_table('vl_custom_script_version')
    engine.dispose()
