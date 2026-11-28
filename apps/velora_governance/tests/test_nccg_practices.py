import pytest
import velora
from velora import get_doc, get_list, new_doc
from velora.permissions import Session, session_as

from velora_governance.setup import seed_governance_codes
from velora_governance.governance.services.nccg_practices import practices


ADMIN = Session("Administrator", frozenset({"System Manager"}))
APPS = ["velora_notify", "velora_erp", "velora_projectone", "velora_admin", "velora_governance"]


@pytest.fixture
def site(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path / 'p.db'}", apps=APPS, developer_mode=True)
    velora.init(); velora.migrate()
    from velora_governance.setup import after_install
    with session_as(ADMIN):
        after_install()
        yield


def _entity():
    t = get_list("Governance Entity Type", fields=["name"], limit=1)[0]["name"]
    return new_doc("Governance Entity", entity_name="Practice Co", legal_name="Practice Company Limited", country="Nigeria", entity_type=t).insert()


def test_practices_cover_all_principles_with_unique_references():
    rows = practices()
    assert len(rows) == len({r[1] for r in rows})
    assert {r[0] for r in rows} == set(range(1, 29))


def test_seed_adds_practices_and_assessment_prefills(site):
    seed_governance_codes()
    name = get_list("Governance Code", filters=[["code_name", "=", "Nigerian Code of Corporate Governance 2018"]], fields=["name"], ignore_permissions=True)[0]["name"]
    code = get_doc("Governance Code", name, ignore_permissions=True)
    assert len(code.practices) == len(practices())
    a = new_doc("Code Compliance Assessment", governance_entity=_entity().name, governance_code=code.name, assessment_period="FY2026")
    a.insert(ignore_permissions=True)
    assert len(a.practice_responses) == len(practices())
    assert a.practice_application_percent == 0
    a.practice_responses[0].status = "Applied in part"
    with pytest.raises(Exception):
        a.save(ignore_permissions=True)
    a.practice_responses[0].status = "Applied"
    a.practice_responses[1].status = "Not applicable"
    a.save(ignore_permissions=True)
    assert a.practice_applied_count == 1 and a.practice_total_count == len(practices()) - 1


def test_screen_api_returns_principles_with_practices_and_saves_answers(site):
    from velora_governance import api
    seed_governance_codes()
    name = get_list("Governance Code", filters=[["code_name", "=", "Nigerian Code of Corporate Governance 2018"]], fields=["name"], ignore_permissions=True)[0]["name"]
    a = new_doc("Code Compliance Assessment", governance_entity=_entity().name, governance_code=name, assessment_period="FY2026").insert(ignore_permissions=True)
    v = api.get_code_assessment(a.name)
    assert len(v["principles"]) == 28 and len(v["principles"][10]["practices"]) > 50     # principle 11 carries the committee practices
    with pytest.raises(Exception, match="explanation"):
        api.save_code_assessment_answers(a.name, practices=[{"reference": "1.1", "status": "Explained (not applied)"}])
    v = api.save_code_assessment_answers(a.name, principles=[{"number": 1, "status": "Applied", "evidence": "Board charter"}],
                                         practices=[{"reference": "1.1", "status": "Applied"}, {"reference": "1.2", "status": "Explained (not applied)", "how": "Sole director until Series B"}])
    assert v["summary"]["applied"] == 1 and v["summary"]["practices_applied"] == 1 and v["summary"]["practices_assessed"] == 2
    with pytest.raises(Exception, match="No practice"):
        api.save_code_assessment_answers(a.name, practices=[{"reference": "99.9", "status": "Applied"}])
