"""Pure report-review operations and safe sustainability report assembly helpers.

Workflow decisions and approval routing remain external/configured in Velora's
shared workflow engine. This module validates data completeness and assembles
content; it does not make approval decisions.
"""
from __future__ import annotations
import html
from datetime import date
from typing import Iterable, Mapping, Any


REVIEW_STATUSES = {"Pending", "In Progress", "Completed", "Rejected", "Returned for Changes"}
ISSUE_STATUSES = {"Open", "In Progress", "Resolved", "Closed"}
ISSUE_SEVERITIES = {"Low", "Medium", "High", "Critical"}


def review_queue(reviews: Iterable[Mapping[str, Any]], *, reviewer=None, status=None, report=None):
    rows = []
    for r in reviews or []:
        if reviewer and r.get("reviewer") != reviewer: continue
        if status and r.get("review_status") != status: continue
        if report and r.get("report") != report: continue
        rows.append(dict(r))
    rows.sort(key=lambda r: (r.get("review_round") or 0, r.get("review_status") or "", r.get("report") or ""))
    counts = {s: sum(1 for r in rows if r.get("review_status") == s) for s in sorted(REVIEW_STATUSES)}
    return {"items": rows, "total": len(rows), "status_counts": counts,
            "pending": counts["Pending"] + counts["In Progress"],
            "returned": counts["Returned for Changes"], "completed": counts["Completed"]}


def validate_review_payload(payload: Mapping[str, Any]):
    status = payload.get("review_status", "Pending")
    if status not in REVIEW_STATUSES: raise ValueError(f"Unsupported review status: {status}")
    if not payload.get("report"): raise ValueError("Report is required")
    if not payload.get("reviewer"): raise ValueError("Reviewer is required")
    if not payload.get("review_role"): raise ValueError("Review role is required")
    round_no = int(payload.get("review_round", 1))
    if round_no < 1: raise ValueError("Review round must be at least 1")
    return {**dict(payload), "review_status": status, "review_round": round_no}


def validate_issue_payload(payload: Mapping[str, Any]):
    severity = payload.get("severity", "Medium")
    status = payload.get("issue_status", "Open")
    if severity not in ISSUE_SEVERITIES: raise ValueError(f"Unsupported severity: {severity}")
    if status not in ISSUE_STATUSES: raise ValueError(f"Unsupported issue status: {status}")
    if not payload.get("report"): raise ValueError("Report is required")
    if not (payload.get("title") or payload.get("issue_title")): raise ValueError("Issue title is required")
    return {**dict(payload), "severity": severity, "issue_status": status}


def report_completeness(report: Mapping[str, Any], sections: Iterable[Mapping[str, Any]], issues: Iterable[Mapping[str, Any]] = ()):
    section_rows = list(sections or [])
    completed = sum(1 for s in section_rows if s.get("section_status") == "Completed" or bool(str(s.get("content") or "").strip()))
    applicable = sum(1 for s in section_rows if s.get("section_status") != "Not Applicable")
    pct = round(completed / applicable * 100, 2) if applicable else 100.0
    open_issues = sum(1 for i in issues or [] if i.get("issue_status", "Open") not in ("Resolved", "Closed"))
    return {"sections_total": len(section_rows), "sections_applicable": applicable,
            "sections_complete": completed, "section_completeness_percent": pct,
            "open_review_issues": open_issues,
            "report_ready_for_finalization": bool(report.get("report_status") in ("Approved", "Finalized", "Published") and pct == 100 and open_issues == 0)}


def _safe(v):
    return html.escape(str(v or ""), quote=True)


def assemble_report_html(*, report: Mapping[str, Any], sections: Iterable[Mapping[str, Any]], reviews: Iterable[Mapping[str, Any]] = (), include_review_notes=False):
    """Create an escaped, print-friendly HTML report. Content is a draft until reviewed."""
    title = report.get("report_title") or report.get("reporting_period") or report.get("name") or "Sustainability Report"
    entity = report.get("governance_entity") or ""
    period = report.get("reporting_period") or ""
    frameworks = report.get("frameworks") or []
    if isinstance(frameworks, str): frameworks = [frameworks]
    parts = ["<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>",
      "<style>body{font:16px/1.55 Arial,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;color:#20252b}h1{font-size:2rem}h2{border-bottom:1px solid #ddd;padding-bottom:.3rem;margin-top:2rem}.meta{color:#555}.section{page-break-inside:avoid;margin:1.5rem 0} @media print{body{max-width:none;margin:0}.section{page-break-inside:avoid}}</style></head><body>",
      f"<h1>{_safe(title)}</h1><div class='meta'><p><strong>Entity:</strong> {_safe(entity)}</p><p><strong>Reporting period:</strong> {_safe(period)}</p><p><strong>Frameworks:</strong> {_safe(', '.join(frameworks))}</p><p><strong>Status:</strong> {_safe(report.get('report_status','Draft'))}</p></div>"]
    for idx, s in enumerate(sections or [], 1):
        heading = s.get("section_title") or s.get("title") or f"Section {idx}"
        content = s.get("content") or s.get("generated_content") or ""
        # Preserve line breaks without interpreting source HTML.
        safe_content = _safe(content).replace("\n", "<br>")
        parts.append(f"<article class='section'><h2>{_safe(heading)}</h2><div>{safe_content}</div></article>")
    if include_review_notes:
        parts.append("<section><h2>Review Notes (Internal)</h2>")
        for r in reviews or []:
            parts.append(f"<p><strong>{_safe(r.get('reviewer'))} — {_safe(r.get('review_status'))}:</strong> {_safe(r.get('comments'))}</p>")
        parts.append("</section>")
    parts.append("<footer><p>Generated draft. Review and approval are required before publication.</p></footer></body></html>")
    return "".join(parts)


def next_revision_number(existing_revisions: Iterable[Mapping[str, Any]]):
    nums = [int(r.get("revision_number") or 0) for r in existing_revisions or []]
    return max(nums, default=0) + 1


def validate_finalization(report: Mapping[str, Any], sections: Iterable[Mapping[str, Any]], issues: Iterable[Mapping[str, Any]] = (), *, approved_review_count=0):
    """Readiness guard only; actual transition/approval must use configured workflow."""
    summary = report_completeness(report, sections, issues)
    blockers = []
    if report.get("report_status") != "Approved": blockers.append("Report must be approved by the configured workflow")
    if summary["section_completeness_percent"] < 100: blockers.append("All applicable report sections must be complete")
    if summary["open_review_issues"]: blockers.append("Open review issues must be resolved or closed")
    if int(approved_review_count or 0) < 1: blockers.append("At least one completed approval review must be recorded")
    return {"eligible": not blockers, "blockers": blockers, "summary": summary}
