"""Board-ready sustainability report publishing helpers.

These helpers prepare publication-ready HTML and validate publication records.
Actual approval routing remains in Velora's configured workflow engine.
"""
from __future__ import annotations

import hashlib
import html
from datetime import date
from typing import Any, Iterable, Mapping


def _safe(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _rows(values: Iterable[Mapping[str, Any]] | None, columns: list[tuple[str, str]]) -> str:
    values = list(values or [])
    if not values:
        return "<p class='empty'>No records available for this section.</p>"
    head = "".join(f"<th>{_safe(label)}</th>" for _, label in columns)
    body = []
    for row in values:
        body.append("<tr>" + "".join(f"<td>{_safe(row.get(key, ''))}</td>" for key, _ in columns) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _metric_cards(metrics: Mapping[str, Any] | None) -> str:
    cards = []
    for label, value in (metrics or {}).items():
        cards.append(f"<div class='metric'><div class='metric-label'>{_safe(label)}</div><div class='metric-value'>{_safe(value)}</div></div>")
    return "<div class='metrics'>" + "".join(cards) + "</div>" if cards else ""


def build_executive_summary(*, report: Mapping[str, Any], summary_metrics: Mapping[str, Any] | None = None,
                            highlights: Iterable[str] = (), risks: Iterable[str] = (), priorities: Iterable[str] = ()) -> str:
    """Return a concise summary block from supplied, verified data without inventing findings."""
    title = report.get("report_title") or "Sustainability performance overview"
    intro = report.get("executive_summary") or report.get("summary") or (
        f"This report presents sustainability performance for {report.get('reporting_period') or 'the reporting period'} "
        f"and covers the configured reporting frameworks and disclosures."
    )
    def list_html(items, empty_message):
        vals = list(items or [])
        return "<ul>" + "".join(f"<li>{_safe(v)}</li>" for v in vals) + "</ul>" if vals else f"<p class='empty'>{_safe(empty_message)}</p>"
    return (f"<section id='executive-summary'><h2>Executive Summary</h2><h3>{_safe(title)}</h3>"
            f"<p>{_safe(intro)}</p>{_metric_cards(summary_metrics)}"
            f"<h3>Key Highlights</h3>{list_html(highlights, 'No highlights provided.') }"
            f"<h3>Key Risks and Challenges</h3>{list_html(risks, 'No risks or challenges provided.') }"
            f"<h3>Management Priorities</h3>{list_html(priorities, 'No management priorities provided.') }</section>")


def assemble_board_report_html(*, report: Mapping[str, Any], sections: Iterable[Mapping[str, Any]],
                              summary_metrics: Mapping[str, Any] | None = None,
                              highlights: Iterable[str] = (), risks: Iterable[str] = (), priorities: Iterable[str] = (),
                              targets: Iterable[Mapping[str, Any]] = (), emissions: Iterable[Mapping[str, Any]] = (),
                              materiality: Iterable[Mapping[str, Any]] = (), disclosures: Iterable[Mapping[str, Any]] = (),
                              evidence_references: Iterable[Mapping[str, Any]] = (), include_draft_watermark: bool = True) -> str:
    """Build a print-friendly board report with TOC, structured appendices and safe escaping."""
    sections = sorted(list(sections or []), key=lambda s: (s.get("sequence") or 0, s.get("section_title") or ""))
    title = report.get("report_title") or report.get("reporting_period") or report.get("name") or "Sustainability Report"
    entity = report.get("governance_entity") or ""
    period = report.get("reporting_period") or ""
    frameworks = report.get("frameworks") or []
    if isinstance(frameworks, str): frameworks = [frameworks]
    elif isinstance(frameworks, (list, tuple)):
        frameworks = [f.get("framework") or f.get("framework_name") or str(f) if isinstance(f, Mapping) else str(f) for f in frameworks]
    draft = include_draft_watermark and report.get("report_status") not in ("Finalized", "Published")
    toc = [("executive-summary", "Executive Summary")]
    section_html = []
    for idx, section in enumerate(sections, 1):
        anchor = f"section-{idx}"
        heading = section.get("section_title") or section.get("title") or f"Section {idx}"
        content = section.get("content") or section.get("generated_content") or ""
        toc.append((anchor, heading))
        section_html.append(f"<article class='report-section' id='{anchor}'><h2>{idx}. {_safe(heading)}</h2><div class='section-content'>{_safe(content).replace(chr(10), '<br>')}</div>")
        if section.get("evidence_reference"):
            section_html.append(f"<p class='source-note'><strong>Evidence reference:</strong> {_safe(section.get('evidence_reference'))}</p>")
        section_html.append("</article>")
    appendices = []
    if targets:
        toc.append(("targets", "Targets and Performance"))
        appendices.append(f"<section id='targets'><h2>Targets and Performance</h2>{_rows(targets, [('target','Target'),('baseline','Baseline'),('target_value','Target Value'),('current_value','Current Value'),('progress_percent','Progress %'),('status','Status')])}</section>")
    if emissions:
        toc.append(("emissions", "GHG Emissions"))
        appendices.append(f"<section id='emissions'><h2>GHG Emissions</h2>{_rows(emissions, [('scope','Scope'),('category','Category'),('activity','Activity'),('quantity','Quantity'),('unit','Unit'),('tco2e','tCO2e')])}</section>")
    if materiality:
        toc.append(("materiality", "Materiality Assessment"))
        appendices.append(f"<section id='materiality'><h2>Materiality Assessment</h2>{_rows(materiality, [('topic','Topic'),('impact_score','Impact Score'),('financial_score','Financial Score'),('materiality','Materiality'),('priority','Priority')])}</section>")
    if disclosures:
        toc.append(("disclosures", "Framework Disclosure Appendix"))
        appendices.append(f"<section id='disclosures'><h2>Framework Disclosure Appendix</h2>{_rows(disclosures, [('framework','Framework'),('disclosure_code','Disclosure Code'),('disclosure','Disclosure'),('status','Status'),('readiness_percent','Readiness %')])}</section>")
    if evidence_references:
        toc.append(("evidence", "Evidence References"))
        appendices.append(f"<section id='evidence'><h2>Evidence References</h2>{_rows(evidence_references, [('reference','Reference'),('description','Description'),('source','Source'),('date','Date')])}</section>")
    toc_html = "<nav class='toc'><h2>Contents</h2><ol>" + "".join(f"<li><a href='#{_safe(anchor)}'>{_safe(label)}</a></li>" for anchor, label in toc) + "</ol></nav>"
    watermark = "<div class='draft-watermark'>DRAFT — NOT FOR DISTRIBUTION</div>" if draft else ""
    css = """body{font:11pt/1.5 Arial,sans-serif;color:#20252b;margin:0 auto;max-width:900px;padding:32px}h1{font-size:28pt}h2{font-size:18pt;border-bottom:1px solid #d9dee5;padding-bottom:6px;margin-top:28px}h3{font-size:13pt}.cover{min-height:60vh;display:flex;flex-direction:column;justify-content:center}.meta{color:#4b5563}.toc{page-break-after:always}.toc li{margin:5px 0}.report-section,section{margin:24px 0;page-break-inside:avoid}.metrics{display:flex;flex-wrap:wrap;gap:12px;margin:18px 0}.metric{border:1px solid #d9dee5;border-radius:6px;padding:12px;min-width:120px}.metric-label{font-size:9pt;color:#555}.metric-value{font-size:16pt;font-weight:bold}table{border-collapse:collapse;width:100%;margin:14px 0}th,td{border:1px solid #cfd5dc;padding:6px 8px;text-align:left;vertical-align:top}th{background:#f2f4f7}.empty{color:#666;font-style:italic}.source-note{font-size:9pt;color:#555}.draft-watermark{position:fixed;top:40%;left:15%;font-size:34pt;color:#ddd;transform:rotate(-25deg);z-index:-1}@media print{body{max-width:none;padding:12mm}.cover{min-height:240mm}.toc{page-break-after:always}a{color:inherit;text-decoration:none}}"""
    meta = (f"<p><strong>Entity:</strong> {_safe(entity)}</p><p><strong>Reporting period:</strong> {_safe(period)}</p>"
            f"<p><strong>Frameworks:</strong> {_safe(', '.join(map(str, frameworks)))}</p><p><strong>Status:</strong> {_safe(report.get('report_status', 'Draft'))}</p>")
    html_doc = ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
                f"<title>{_safe(title)}</title><style>{css}</style></head><body>{watermark}"
                f"<header class='cover'><h1>{_safe(title)}</h1><div class='meta'>{meta}</div><p>Prepared for Board and Executive Management</p></header>"
                f"{toc_html}{build_executive_summary(report=report, summary_metrics=summary_metrics, highlights=highlights, risks=risks, priorities=priorities)}"
                f"{''.join(section_html)}{''.join(appendices)}<footer><p>Generated report draft. Confirm source data, review, approval and disclosure applicability before publication.</p></footer></body></html>")
    return html_doc


def validate_publication_payload(payload: Mapping[str, Any], *, report: Mapping[str, Any],
                                sections: Iterable[Mapping[str, Any]], open_issue_count: int = 0,
                                approved_review_count: int = 0) -> dict[str, Any]:
    """Validate publication metadata; does not execute workflow transitions."""
    blockers = []
    status = report.get("report_status")
    if status not in ("Finalized", "Published"):
        blockers.append("Report must be finalized through the configured workflow before publication")
    incomplete = [s for s in (sections or []) if s.get("section_status") != "Not Applicable" and not (
        s.get("section_status") == "Completed" or bool(str(s.get("content") or "").strip()))]
    if incomplete:
        blockers.append(f"{len(incomplete)} applicable report section(s) are incomplete")
    if int(open_issue_count or 0):
        blockers.append("Open review issues must be resolved before publication")
    if int(approved_review_count or 0) < 1:
        blockers.append("At least one completed approval review must be recorded")
    channel = payload.get("publication_channel")
    if not channel:
        blockers.append("Publication channel is required")
    pub_date = payload.get("publication_date") or date.today().isoformat()
    return {"eligible": not blockers, "blockers": blockers,
            "publication_channel": channel, "publication_date": pub_date,
            "audience": payload.get("audience") or "Board and Executive Management",
            "publication_url": payload.get("publication_url"), "file_reference": payload.get("file_reference"),
            "notes": payload.get("notes") or ""}


def publication_digest(content: str) -> str:
    """Return a stable SHA-256 digest for a published content snapshot."""
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()
