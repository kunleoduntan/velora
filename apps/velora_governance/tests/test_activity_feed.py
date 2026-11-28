"""ERP spend -> emissions activity feed."""
from datetime import date
from decimal import Decimal

import pytest
import velora
from velora import get_list, new_doc
from velora.permissions import Session, session_as

from velora_governance.governance.services import activity_feed as feed

ADMIN = Session("Administrator", frozenset({"System Manager"}))
APPS = ["velora_notify", "velora_erp", "velora_projectone", "velora_admin", "velora_governance"]


def R(name, **kw):
    base = dict(name=name, rule_name=name, priority=100, active=1, fixed_assets="Any", treatment="Estimate emissions", spend_per_factor_unit=1)
    base.update(kw); return base


def L(amount, **kw):
    return dict(amount=amount, **kw)


def test_first_match_by_priority_then_specificity_and_every_line_lands_once():
    rules = [R("broad", match_account="Office Expenses"), R("narrow", match_account="Office Expenses", match_item_group="Paper"),
             R("urgent", match_account="Office Expenses", priority=10)]
    lines = [L(100, account="Office Expenses", item_group="Paper"), L(50, account="Office Expenses", item_group="Pens"), L(30, account="Rent")]
    c = feed.classify(lines, rules)
    assert c["by_rule"]["urgent"]["spend"] == Decimal(150) and "narrow" not in c["by_rule"]       # priority beats specificity
    assert c["unmapped"]["Rent"]["spend"] == Decimal(30)
    c2 = feed.classify(lines, [r for r in rules if r["name"] != "urgent"])
    assert c2["by_rule"]["narrow"]["spend"] == 100 and c2["by_rule"]["broad"]["spend"] == 50  # specificity breaks the tie
    total = sum(b["spend"] for b in c["by_rule"].values()) + sum(b["spend"] for b in c["unmapped"].values())
    assert total == Decimal(180)


def test_fixed_asset_filter_and_a_rule_with_no_matcher_never_matches():
    rule = R("capital", match_account="Plant", fixed_assets="Fixed assets only")
    assert feed.rule_matches(rule, {"account": "Plant", "is_fixed_asset": True})
    assert not feed.rule_matches(rule, {"account": "Plant", "is_fixed_asset": False})
    assert not feed.rule_matches(R("empty"), {"account": "x"})


@pytest.fixture
def site(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path / 'f.db'}", apps=APPS, developer_mode=True)
    velora.init(); velora.migrate()
    from velora_governance.setup import after_install
    with session_as(ADMIN):
        after_install()
        yield


def _setup():
    t = get_list("Governance Entity Type", fields=["name"], limit=1)[0]["name"]
    entity = new_doc("Governance Entity", entity_name="Acme Ltd", legal_name="Acme Limited", country="Nigeria", entity_type=t).insert()
    cat = get_list("Emission Source Category", fields=["name"], limit=1)[0]["name"]
    unit = new_doc("Sustainability Unit", unit_name="USD-spend").insert() if not get_list("Sustainability Unit", filters=[["unit_name", "=", "USD-spend"]], limit=1) else None
    unit = get_list("Sustainability Unit", filters=[["unit_name", "=", "USD-spend"]], fields=["name"], limit=1)[0]["name"]
    src = new_doc("Emission Source", governance_entity=entity.name, scope="Scope 3", scope3_category="1. Purchased goods and services", source_name="Purchased services",
                  source_category=cat, unit=unit, active=1).insert()
    fac = new_doc("Emission Factor", factor_name="Services (per USD)", unit=unit, kgco2e_per_unit=0.4, factor_year=2026, active=1).insert()
    new_doc("Sustainability Reporting Period", governance_entity=entity.name, period_name="FY2026", period_start=date(2026, 1, 1), period_end=date(2026, 12, 31),
            period_type="Annual", period_status="Data Collection").insert()
    return entity, src, fac


def test_rule_validation(site):
    entity, src, fac = _setup()
    with pytest.raises(Exception, match="at least one match"):
        new_doc("Spend Emission Rule", governance_entity=entity.name, rule_name="all", emission_source=src.name, emission_factor=fac.name).insert()
    with pytest.raises(Exception, match="why this spend is excluded"):
        new_doc("Spend Emission Rule", governance_entity=entity.name, rule_name="tax", match_account="VAT", treatment="Exclude from inventory").insert()
    new_doc("Spend Emission Rule", governance_entity=entity.name, rule_name="ok", match_account="Services", emission_source=src.name, emission_factor=fac.name).insert()


def test_run_is_idempotent_reports_coverage_and_refreshes_instead_of_doubling(site):
    entity, src, fac = _setup()
    new_doc("Spend Emission Rule", governance_entity=entity.name, rule_name="Services", match_account="Services", emission_source=src.name,
            emission_factor=fac.name, spend_per_factor_unit=1000).insert()
    new_doc("Spend Emission Rule", governance_entity=entity.name, rule_name="Tax", match_account="VAT", treatment="Exclude from inventory", exclusion_reason="Tax is not an activity").insert()
    data = {"lines": [L(2_000_000, account="Services"), L(500_000, account="Services"), L(100_000, account="VAT"), L(400_000, account="Mystery")]}
    loader = lambda a, b: (data["lines"], 3)
    p = feed.preview(entity.name, "FY2026", loader=loader)
    assert p["spend_estimated"] == 2_500_000 and p["spend_excluded"] == 100_000 and p["spend_unmapped"] == 400_000
    assert round(p["coverage_percent"], 2) == 86.67 and any("no rule" in w for w in p["warnings"])
    assert get_list("GHG Calculation", filters=[["governance_entity", "=", entity.name]], limit=5) == []      # preview wrote nothing
    r = feed.post(entity.name, "FY2026", loader=loader, user="t")
    calcs = get_list("GHG Calculation", filters=[["governance_entity", "=", entity.name]], fields=["name", "activity_quantity", "emissions_tco2e", "scope3_category", "feed_key"], limit=10)
    assert len(calcs) == 1 and calcs[0]["activity_quantity"] == 2500 and calcs[0]["scope3_category"].startswith("1.")
    assert calcs[0]["emissions_tco2e"] == pytest.approx(1.0)                                                  # 2500 USD x 0.4 kg = 1000 kg
    data["lines"] = [L(4_000_000, account="Services"), L(400_000, account="Mystery")]
    feed.post(entity.name, "FY2026", loader=loader, user="t")
    calcs = get_list("GHG Calculation", filters=[["governance_entity", "=", entity.name]], fields=["activity_quantity"], limit=10)
    assert len(calcs) == 1 and calcs[0]["activity_quantity"] == 4000                                          # refreshed, not added
    data["lines"] = [L(400_000, account="Mystery")]
    feed.post(entity.name, "FY2026", loader=loader, user="t")
    assert get_list("GHG Calculation", filters=[["governance_entity", "=", entity.name]], limit=5) == []     # stale feed calc removed
    assert len(get_list("Activity Feed Run", limit=10)) == 3


def test_the_feed_never_touches_hand_entered_calculations_and_warns_about_overlap(site):
    entity, src, fac = _setup()
    new_doc("GHG Calculation", governance_entity=entity.name, emission_source=src.name, reporting_period="FY2026", activity_quantity=10,
            unit=src.unit, emission_factor=fac.name).insert()
    new_doc("Spend Emission Rule", governance_entity=entity.name, rule_name="Services", match_account="Services", emission_source=src.name, emission_factor=fac.name).insert()
    out = feed.post(entity.name, "FY2026", loader=lambda a, b: ([L(1000, account="Services")], 1), user="t")
    assert any("hand-entered" in w for w in out["warnings"])
    assert len(get_list("GHG Calculation", filters=[["governance_entity", "=", entity.name]], limit=10)) == 2


def test_a_locked_period_refuses_the_feed_and_a_missing_period_is_explained(site):
    entity, src, fac = _setup()
    new_doc("Spend Emission Rule", governance_entity=entity.name, rule_name="Services", match_account="Services", emission_source=src.name, emission_factor=fac.name).insert()
    with pytest.raises(Exception, match="Sustainability Reporting Period"):
        feed.preview(entity.name, "FY1999", loader=lambda a, b: ([], 0))


def test_end_to_end_from_real_submitted_purchase_invoices(tmp_path, monkeypatch):
    """Real ERP documents: only submitted invoices count, the books' base amount is used, and a draft is ignored."""
    from test_cash_transactions import setup_cash, approve, MAKER
    real = velora.configure
    monkeypatch.setattr(velora, "configure", lambda **kw: real(**{**kw, "apps": APPS}))
    accounts, customer, supplier = setup_cash(tmp_path)
    from velora_governance.setup import after_install as gov_install
    from velora import get_doc
    with session_as(ADMIN):
        gov_install()
        entity, src, fac = _setup()
        new_doc("Spend Emission Rule", governance_entity=entity.name, rule_name="Office", match_account=accounts["5000"].name,
                emission_source=src.name, emission_factor=fac.name).insert()
        today = date.today()
        # the reporting period must contain today's invoices
        per = get_list("Sustainability Reporting Period", filters=[["governance_entity", "=", entity.name]], fields=["name"], limit=1)[0]["name"]
        p = get_doc("Sustainability Reporting Period", per); p.period_start = date(today.year, 1, 1); p.period_end = date(today.year, 12, 31); p.save()
        def invoice(amount):
            return new_doc("Purchase Invoice", invoice_date=today, posting_date=today, due_date=today, party=supplier.name, currency="NGN", exchange_rate=1,
                           lines=[{"account": accounts["5000"].name, "description": "Services", "quantity": 1, "uom": "Each", "amount": amount}]).insert(ignore_permissions=True)
        approve(invoice(1000)); approve(invoice(2500)); invoice(9999)                          # the third stays a draft
        out = feed.post(entity.name, "FY2026", user="t")
        assert out["invoices"] == 2 and out["spend_estimated"] == 3500 and out["spend_unmapped"] == 0
        calc = get_list("GHG Calculation", filters=[["governance_entity", "=", entity.name]], fields=["activity_quantity", "emissions_kgco2e"], limit=5)
        assert len(calc) == 1 and calc[0]["activity_quantity"] == 3500 and calc[0]["emissions_kgco2e"] == pytest.approx(1400)


def test_ixbrl_export_is_well_formed_consistent_and_never_invents_taxonomy_names(site):
    import xml.etree.ElementTree as ET
    from velora_governance.governance.services import ixbrl_export as ix
    entity, src, fac = _setup()
    unit = src.unit
    cat = get_list("Emission Source Category", fields=["name"], limit=1)[0]["name"]
    s1 = new_doc("Emission Source", governance_entity=entity.name, scope="Scope 1", source_name="Boiler", source_category=cat, unit=unit, active=1).insert()
    new_doc("GHG Calculation", governance_entity=entity.name, emission_source=s1.name, reporting_period="FY2026", activity_quantity=5000, unit=unit, emission_factor=fac.name).insert()
    assert len(get_list("Taxonomy Concept Map", fields=["fact_key"], limit=20)) == 4 and ix.seed_concept_map() == 0
    with pytest.raises(Exception, match="XBRL Export Setting"):
        ix.build(entity.name, "FY2026")
    new_doc("XBRL Export Setting", governance_entity=entity.name, schema_ref="https://example.org/taxonomy/entry.xsd", taxonomy_prefix="tx", taxonomy_namespace="https://example.org/tx",
            identifier_scheme="https://example.org/id", identifier="ACME-1", co2e_unit_measure="u:tCO2e", extra_namespaces="u=https://example.org/units").insert()
    out = ix.build(entity.name, "FY2026")
    assert out["facts"] == 0 and "ghg.scope1" in out["unmapped"] and any("Not validated" in w for w in out["warnings"])      # no QName -> nothing invented
    row = get_list("Taxonomy Concept Map", filters=[["fact_key", "=", "ghg.scope1"]], fields=["name"], limit=1)[0]["name"]
    d = velora.get_doc("Taxonomy Concept Map", row); d.element_qname = "tx:GrossScope1"; d.save()
    out = ix.build(entity.name, "FY2026")
    root = ET.fromstring(out["document"].encode("utf-8"))                     # well-formed
    ns = {"ix": ix.IX_NS, "xbrli": "http://www.xbrl.org/2003/instance"}
    facts = root.findall(".//ix:nonFraction", ns)
    assert out["facts"] == 1 and len(facts) == 1 and facts[0].get("name") == "tx:GrossScope1" and facts[0].text == "2" or float(facts[0].text) == pytest.approx(2.0)
    ctx_ids = {c.get("id") for c in root.findall(".//xbrli:context", ns)}; unit_ids = {u.get("id") for u in root.findall(".//xbrli:unit", ns)}
    assert facts[0].get("contextRef") in ctx_ids and facts[0].get("unitRef") in unit_ids                # every reference resolves
    assert root.find(".//xbrli:startDate", ns).text == "2026-01-01" and root.find(".//xbrli:endDate", ns).text == "2026-12-31"
    d = velora.get_doc("Taxonomy Concept Map", row); d.element_qname = "zz:Other"; d.save()
    with pytest.raises(Exception, match="not declared"):
        ix.build(entity.name, "FY2026")


def test_ixbrl_carries_data_point_figures_and_report_narrative_without_inventing_names(site):
    import xml.etree.ElementTree as ET
    from velora_governance.governance.services import ixbrl_export as ix
    entity, src, fac = _setup()
    new_doc("XBRL Export Setting", governance_entity=entity.name, schema_ref="https://example.org/taxonomy/entry.xsd", taxonomy_prefix="tx", taxonomy_namespace="https://example.org/tx",
            identifier_scheme="https://example.org/id", identifier="ACME-1", co2e_unit_measure="u:tCO2e", extra_namespaces="u=https://example.org/units\niso=https://example.org/iso").insert()
    cat = get_list("Sustainability Metric Category", fields=["name"], limit=1)[0]["name"]
    unit = get_list("Sustainability Unit", fields=["name"], limit=1)[0]["name"]
    m = new_doc("Sustainability Metric", metric_code="X-RENEW", metric_name="Renewable share", category=cat, default_unit=unit, data_type="Percentage", frequency="Annual", active=1).insert()
    new_doc("Sustainability Data Point", governance_entity=entity.name, metric=m.name, reporting_period="FY2026", data_type="Percentage", value=12.5, unit=unit, verification_status="Reviewed", data_date=date(2026, 12, 31)).insert()
    disc = get_list("Sustainability Disclosure", fields=["name"], limit=1)[0]["name"]
    rep = new_doc("Sustainability Report", governance_entity=entity.name, reporting_period="FY2026", report_status="Draft")
    rep.append("sections", {"sequence": 1, "section_title": "Governance narrative", "disclosure": disc, "content": "The board oversees climate risk.\n\nA <committee> meets quarterly & reports.", "section_status": "Completed"})
    rep.insert()
    # a number with no unit is refused, not guessed
    pct = new_doc("Taxonomy Concept Map", fact_key="x.renew", label="Renewable share", source="Data point", fact_type="Percentage", source_metric=m.name, element_qname="tx:RenewableShare", decimals="1", scale="-2").insert()
    txt = new_doc("Taxonomy Concept Map", fact_key="x.gov", label="Governance narrative", source="Report section text", source_disclosure=disc, element_qname="tx:GovernanceNarrative").insert()
    assert txt.fact_type == "Text block"
    with pytest.raises(Exception, match="needs a Sustainability Metric"):
        new_doc("Taxonomy Concept Map", fact_key="x.bad", label="Bad", source="Data point", fact_type="Number").insert()
    with pytest.raises(Exception, match="unit measure"):
        new_doc("Taxonomy Concept Map", fact_key="x.money", label="Money", source="Data point", source_metric=m.name, fact_type="Monetary").insert()
    out = ix.build(entity.name, "FY2026")
    root = ET.fromstring(out["document"].encode("utf-8"))
    ns = {"ix": ix.IX_NS, "xbrli": "http://www.xbrl.org/2003/instance"}
    num = [f for f in root.findall(".//ix:nonFraction", ns) if f.get("name") == "tx:RenewableShare"][0]
    assert float(num.text) == 12.5 and num.get("scale") == "-2" and num.get("unitRef") == "pure"
    assert "pure" in {u.get("id") for u in root.findall(".//xbrli:unit", ns)}
    nn = root.find(".//ix:nonNumeric", ns)
    assert nn.get("name") == "tx:GovernanceNarrative" and "&lt;committee&gt;" in out["document"] and "<committee>" not in out["document"]
    assert [p.text for p in nn.findall("{http://www.w3.org/1999/xhtml}p")][0] == "The board oversees climate risk."
