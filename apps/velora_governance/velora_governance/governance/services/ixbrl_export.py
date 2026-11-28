"""Inline XBRL (iXBRL) export of the GHG facts, data-point figures and report-section narrative text.

What this does: builds a well-formed Inline XBRL 1.1 XHTML document, with ix:header, contexts, a unit and ix:nonFraction facts,
from the GHG inventory and the entity's Taxonomy Concept Map.

What it does not do, on purpose: it does not invent taxonomy identifiers. The element names, namespace, entry-point URL and unit
measure come from the taxonomy release you file against and are entered in XBRL Export Setting and Taxonomy Concept Map. A fact
with no element QName is listed as unmapped and not exported. The output has not been validated against the taxonomy by this
software: validate it with an XBRL processor (for example Arelle) and the regulator's filing rules before filing.
"""
from __future__ import annotations

import html
from decimal import Decimal

from velora import get_list, throw

IX_NS = "http://www.xbrl.org/2013/inlineXBRL"
FACTS = [   # (fact_key, label as printed in the ISSB taxonomy guide, ISSB metric code (verified for the three marked), inventory key)
    ("ghg.scope1", "Absolute gross Scope 1 GHG emissions", "S2.29.a.i.1.1", "scope1_tco2e"),
    ("ghg.scope2.location", "Absolute gross location-based Scope 2 GHG emissions", "S2.29.a.i.2.1", "scope2_location_tco2e"),
    ("ghg.scope2.market", "Absolute gross market-based Scope 2 GHG emissions", "", "scope2_market_tco2e"),
    ("ghg.scope3", "Absolute gross Scope 3 GHG emissions", "S2.29.a.i.3.1", "scope3_tco2e"),
]


def seed_concept_map() -> int:
    """Create the fact rows (label and metric code only). Element QNames are left blank for the preparer to copy from the taxonomy."""
    from velora import new_doc
    have = {r["fact_key"] for r in get_list("Taxonomy Concept Map", fields=["fact_key"], limit=1000, ignore_permissions=True)}
    n = 0
    for key, label, code, _ in FACTS:
        if key not in have:
            new_doc("Taxonomy Concept Map", fact_key=key, label=label, metric_code=code, decimals="0", active=1).insert(ignore_permissions=True)
            n += 1
    return n


def _esc(v):
    return html.escape(str(v), quote=True)


def build(entity, reporting_period, *, entity_label=None) -> dict:
    s = get_list("XBRL Export Setting", filters=[["governance_entity", "=", entity]], fields=["schema_ref", "taxonomy_prefix", "taxonomy_namespace", "identifier_scheme", "identifier",
                 "co2e_unit_id", "co2e_unit_measure", "extra_namespaces"], limit=1, ignore_permissions=True)
    if not s:
        throw("Create an XBRL Export Setting for this entity first (taxonomy entry point, namespace, entity identifier and CO2e unit measure).")
    s = s[0]
    per = get_list("Sustainability Reporting Period", filters=[["governance_entity", "=", entity], ["period_name", "=", reporting_period]], fields=["period_start", "period_end"], limit=1, ignore_permissions=True)
    if not per:
        throw(f"No Sustainability Reporting Period named '{reporting_period}' for this entity.")
    from velora_governance.governance.services.ghg_accounting import inventory_for
    inv = inventory_for(entity, reporting_period)
    cmap = {r["fact_key"]: r for r in get_list("Taxonomy Concept Map", filters=[["active", "=", 1]],
            fields=["fact_key", "label", "metric_code", "element_qname", "decimals", "source", "fact_type", "source_metric", "source_disclosure", "unit_id", "unit_measure", "scale"], limit=1000, ignore_permissions=True)}
    facts, unmapped, nodata = [], [], []
    for key, label, code, inv_key in FACTS:
        value = inv.get(inv_key)
        row = cmap.get(key)
        if value in (None, "") or Decimal(str(value)) == 0 and not inv.get("calculation_count"):
            nodata.append(key); continue
        if not row or not row.get("element_qname"):
            unmapped.append(key); continue
        facts.append({"key": key, "label": row.get("label") or label, "qname": row["element_qname"], "value": Decimal(str(value)), "decimals": row.get("decimals") or "0"})
    extra_facts, extra_units = _other_facts(entity, reporting_period, cmap, unmapped, nodata)
    facts.extend(extra_facts)
    extra = dict(l.split("=", 1) for l in (s.get("extra_namespaces") or "").splitlines() if "=" in l)
    ns = {"xhtml": None, "ix": IX_NS, "xbrli": "http://www.xbrl.org/2003/instance", "link": "http://www.xbrl.org/2003/linkbase", "xlink": "http://www.w3.org/1999/xlink",
          s["taxonomy_prefix"]: s["taxonomy_namespace"]}
    ns.update({k.strip(): v.strip() for k, v in extra.items()})
    for f in facts:                                   # every prefix used in a QName must be declared
        prefix = f["qname"].split(":")[0]
        if prefix not in ns:
            throw(f"Element {f['qname']} uses prefix '{prefix}', which is not declared. Add it to XBRL Export Setting.")
    uprefix = s["co2e_unit_measure"].split(":")[0] if ":" in s["co2e_unit_measure"] else None
    if uprefix and uprefix not in ns:
        throw(f"The unit measure uses prefix '{uprefix}', which is not declared. Add it under 'Other namespace prefixes'.")
    for u in extra_units.values():
        up = u["measure"].split(":")[0] if ":" in u["measure"] else None
        if up and up not in ns and up != "xbrli":
            throw(f"Unit measure {u['measure']} uses prefix '{up}', which is not declared. Add it under 'Other namespace prefixes'.")
    decl = " ".join(f'xmlns:{k}="{_esc(v)}"' for k, v in ns.items() if k != "xhtml")
    ctx = "c-period"
    body = []
    for f in facts:
        if f.get("kind") == "text":
            body.append(f'<tr><td>{_esc(f["label"])}</td><td><ix:nonNumeric name="{_esc(f["qname"])}" contextRef="{ctx}">{f["html"]}</ix:nonNumeric></td></tr>')
            continue
        if f.get("kind") == "number":
            sc = f' scale="{_esc(f["scale"])}"' if f.get("scale") else ""
            body.append(f'<tr><td>{_esc(f["label"])}</td><td><ix:nonFraction name="{_esc(f["qname"])}" contextRef="{ctx}" unitRef="{_esc(f["unit_id"])}" decimals="{_esc(f["decimals"])}"{sc}>{f["value"].normalize():f}</ix:nonFraction>{_esc(" " + f["suffix"]) if f.get("suffix") else ""}</td></tr>')
            continue
        body.append(f'<tr><td>{_esc(f["label"])}</td><td><ix:nonFraction name="{_esc(f["qname"])}" contextRef="{ctx}" unitRef="{_esc(s.get("co2e_unit_id") or "tCO2e")}" decimals="{_esc(f["decimals"])}">{f["value"].normalize():f}</ix:nonFraction> tCO2e</td></tr>')
    title = f"{entity_label or entity} - GHG emissions, {reporting_period}"
    doc = (f'<?xml version="1.0" encoding="utf-8"?>\n<html xmlns="http://www.w3.org/1999/xhtml" {decl}>\n<head><meta http-equiv="Content-Type" content="text/html; charset=utf-8"/><title>{_esc(title)}</title></head>\n<body>\n'
           f'<div style="display:none"><ix:header><ix:references><link:schemaRef xlink:type="simple" xlink:href="{_esc(s["schema_ref"])}"/></ix:references><ix:resources>'
           f'<xbrli:context id="{ctx}"><xbrli:entity><xbrli:identifier scheme="{_esc(s["identifier_scheme"])}">{_esc(s["identifier"])}</xbrli:identifier></xbrli:entity>'
           f'<xbrli:period><xbrli:startDate>{per[0]["period_start"]}</xbrli:startDate><xbrli:endDate>{per[0]["period_end"]}</xbrli:endDate></xbrli:period></xbrli:context>'
           f'<xbrli:unit id="{_esc(s.get("co2e_unit_id") or "tCO2e")}"><xbrli:measure>{_esc(s["co2e_unit_measure"])}</xbrli:measure></xbrli:unit>'
           + "".join(f'<xbrli:unit id="{_esc(uid)}"><xbrli:measure>{_esc(u["measure"])}</xbrli:measure></xbrli:unit>' for uid, u in extra_units.items()) +
           f'</ix:resources></ix:header></div>\n'
           f'<h1>{_esc(title)}</h1>\n<table border="1"><tr><th>Disclosure</th><th>Amount</th></tr>\n' + "\n".join(body) + "\n</table>\n"
           f'<p>Organisational boundary: {_esc(inv.get("organisational_boundary") or "not stated")}. Measured under the GHG Protocol Corporate Standard.</p>\n</body></html>\n')
    warnings = list(inv.get("warnings") or [])
    if unmapped:
        warnings.append("Not exported, no element QName in Taxonomy Concept Map: " + ", ".join(unmapped))
    if not facts:
        warnings.append("No facts were exported.")
    warnings.append("Not validated against the taxonomy by this software. Validate with an XBRL processor and the regulator's filing rules before filing.")
    return {"document": doc, "facts": len(facts), "unmapped": unmapped, "no_data": nodata, "warnings": warnings}


def _other_facts(entity, reporting_period, cmap, unmapped, nodata):
    """Facts beyond the four GHG totals: figures from data points and narrative text from report sections, as set up in the Taxonomy Concept Map."""
    out, units = [], {}
    builtin = {k for k, *_ in FACTS}
    report_sections = None
    for key, row in cmap.items():
        if key in builtin:
            continue
        if not row.get("element_qname"):
            unmapped.append(key); continue
        src = row.get("source") or "GHG inventory"
        if src == "Data point":
            dps = get_list("Sustainability Data Point", filters=[["governance_entity", "=", entity], ["metric", "=", row["source_metric"]], ["reporting_period", "=", reporting_period]],
                           fields=["value", "text_value", "verification_status"], limit=5, ignore_permissions=True)
            dps = [d for d in dps if d.get("verification_status") != "Rejected" and d.get("value") is not None]
            if not dps:
                nodata.append(key); continue
            ftype = row.get("fact_type") or "Number"
            uid = row.get("unit_id") or ("pure" if ftype == "Percentage" else "")
            measure = row.get("unit_measure") or ("xbrli:pure" if ftype == "Percentage" else "")
            if not uid or not measure:
                throw(f"Fact {key}: a number needs a unit id and unit measure in the Taxonomy Concept Map (the taxonomy decides which unit applies).")
            units[uid] = {"measure": measure}
            out.append({"kind": "number", "key": key, "label": row.get("label") or key, "qname": row["element_qname"], "value": Decimal(str(dps[0]["value"])),
                        "decimals": row.get("decimals") or "0", "scale": row.get("scale") or "", "unit_id": uid, "suffix": "%" if ftype == "Percentage" else ""})
        elif src == "Report section text":
            if report_sections is None:
                reports = get_list("Sustainability Report", filters=[["governance_entity", "=", entity], ["reporting_period", "=", reporting_period]], fields=["name", "report_status"], limit=20, ignore_permissions=True)
                reports = [r for r in reports if r.get("report_status") != "Archived"]
                from velora import get_doc
                report_sections = []
                for r in reports:
                    report_sections.extend(get_doc("Sustainability Report", r["name"], ignore_permissions=True).get("sections") or [])
            texts = [(sec.content or "").strip() for sec in report_sections if sec.disclosure == row["source_disclosure"] and (sec.content or "").strip()]
            if not texts:
                nodata.append(key); continue
            paras = "".join(f"<p>{_esc(t_)}</p>" for t in texts for t_ in [x for x in t.split("\n\n") if x.strip()])
            out.append({"kind": "text", "key": key, "label": row.get("label") or key, "qname": row["element_qname"], "html": paras})
    return out, units
