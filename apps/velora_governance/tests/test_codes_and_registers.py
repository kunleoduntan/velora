"""NCCG 2018 apply-and-explain assessment and the seeded statutory register types."""
import pytest
import velora
from velora import get_doc, get_list, new_doc
from velora.permissions import Session, session_as

ADMIN = Session("Administrator", frozenset({"System Manager"}))
APPS = ["velora_notify", "velora_erp", "velora_projectone", "velora_admin", "velora_governance"]


@pytest.fixture
def site(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path / 'g.db'}", apps=APPS, developer_mode=True)
    velora.init(); velora.migrate()
    from velora_governance.setup import after_install
    with session_as(ADMIN):
        after_install()
        yield


def test_the_nigerian_code_is_seeded_once_with_28_principles_in_six_parts(site):
    from velora_governance.setup import seed_governance_codes
    assert seed_governance_codes() == 0                                           # idempotent
    codes = get_list("Governance Code", fields=["name"], limit=10)
    assert len(codes) == 1
    code = get_doc("Governance Code", codes[0]["name"])
    assert [p.principle_number for p in code.principles] == list(range(1, 29))
    assert len({p.part for p in code.principles}) == 6
    assert code.principles[16].title == "Risk Management" and code.principles[25].title == "Sustainability"


def test_statutory_register_types_include_the_companies_act_registers(site):
    names = {r["register_type_name"] for r in get_list("Statutory Register Type", fields=["register_type_name"], limit=100)}
    assert {"Persons with Significant Control", "Debenture Holders", "Directors' Interests in Shares and Debentures", "Minutes of Board Meetings", "Charges"} <= names


def test_an_assessment_starts_with_every_principle_and_demands_an_explanation_for_departures(site):
    t = get_list("Governance Entity Type", fields=["name"], limit=1)[0]["name"]
    entity = new_doc("Governance Entity", entity_name="Acme Ltd", legal_name="Acme Limited", country="Nigeria", entity_type=t).insert()
    code = get_list("Governance Code", fields=["name"], limit=1)[0]["name"]
    a = new_doc("Code Compliance Assessment", governance_entity=entity.name, governance_code=code, assessment_period="FY2026").insert()
    assert len(a.responses) == 28 and a.not_assessed_count == 28 and a.application_percent == 0
    a.responses[0].status = "Applied"; a.responses[1].status = "Applied"
    a.responses[2].status = "Explained (not applied)"
    with pytest.raises(Exception, match="give the explanation"):
        a.save()
    a.responses[2].how_applied_or_explanation = "The roles of Chairman and CEO are combined for now; separation is planned for the next AGM."
    a.save()
    a.reload()
    assert (a.applied_count, a.explained_count, a.not_assessed_count) == (2, 1, 25) and a.application_percent == pytest.approx(7.14)
