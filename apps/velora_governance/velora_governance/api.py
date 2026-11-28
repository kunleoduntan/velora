"""Permission-checked sustainability reporting API."""
from velora_governance.runtime import host as frappe


def _save_private_file(filename, content, doctype, docname):
    """Attach the generated export to the report through the framework's own file store (private, checksummed, permission-checked)."""
    from types import SimpleNamespace
    from velora.files import add_attachment
    row = add_attachment(content, filename, doctype=doctype, docname=docname)
    return SimpleNamespace(name=row["id"], file_url=f"/api/files/{row['id']}")



def run_sustainability_reporting_period(reporting_period_name):
    if frappe is None:
        raise RuntimeError("Velora framework runtime is required")
    if not frappe.has_permission("Sustainability Reporting Period", "write", reporting_period_name):
        frappe.throw("You do not have permission to generate this reporting period", frappe.PermissionError)
    from velora_governance.governance.services.reporting_persistence import orchestrate_and_persist
    return orchestrate_and_persist(reporting_period_name)

if frappe is not None:
    run_sustainability_reporting_period = frappe.whitelist()(run_sustainability_reporting_period)


def get_sustainability_reporting_dashboard(governance_entity=None, reporting_period=None, framework=None):
    """Permission-aware executive dashboard with entity, period and framework filters."""
    if frappe is None:
        raise RuntimeError("Velora framework runtime is required")
    filters = {}
    if governance_entity:
        if not frappe.has_permission("Governance Entity", "read", governance_entity):
            frappe.throw("You do not have permission to view this governance entity", frappe.PermissionError)
        filters["governance_entity"] = governance_entity
    if reporting_period:
        if not frappe.has_permission("Sustainability Reporting Period", "read", reporting_period):
            frappe.throw("You do not have permission to view this reporting period", frappe.PermissionError)
        filters["name"] = reporting_period
    periods = frappe.get_list("Sustainability Reporting Period", filters=filters,
        fields=["name", "period_name", "period_status", "period_owner", "governance_entity"], limit_page_length=0)
    period_names = [p.get("name") for p in periods]
    if not period_names:
        from velora_governance.governance.services.reporting_dashboard import build_reporting_dashboard
        return build_reporting_dashboard([], [], [], [])
    assessments = frappe.get_list("Sustainability Disclosure Assessment",
        filters={"reporting_period": ["in", period_names]},
        fields=["reporting_period", "disclosure", "applicable", "assessment_status", "readiness_percent", "gap_summary", "disclosure_owner", "due_date"], limit_page_length=0)
    disclosures = frappe.get_list("Sustainability Disclosure", fields=["name", "framework"], limit_page_length=0)
    framework_by_disclosure = {d.get("name"): d.get("framework") for d in disclosures}
    if framework:
        if not frappe.has_permission("Sustainability Framework", "read", framework):
            frappe.throw("You do not have permission to view this sustainability framework", frappe.PermissionError)
        allowed_disclosures = {d.get("name") for d in disclosures if d.get("framework") == framework}
        assessments = [a for a in assessments if a.get("disclosure") in allowed_disclosures]
        # Keep only reporting periods with assessments in the selected framework.
        used_periods = {a.get("reporting_period") for a in assessments}
        periods = [p for p in periods if p.get("name") in used_periods]
        period_names = [p.get("name") for p in periods]
    task_filters = {"reporting_period": ["in", period_names]}
    if framework:
        task_filters["disclosure"] = ["in", list(allowed_disclosures)] if allowed_disclosures else ["in", []]
    tasks = frappe.get_list("Sustainability Data Collection Task",
        filters=task_filters,
        fields=["reporting_period", "task_status", "responsible_owner", "disclosure"], limit_page_length=0)
    report_period_names = [p.get("period_name") for p in periods]
    reports = frappe.get_list("Sustainability Report",
        filters={"reporting_period": ["in", report_period_names]},
        fields=["reporting_period", "report_status", "readiness_percent"], limit_page_length=0)
    reviews = frappe.get_list("Sustainability Report Review",
        filters={"reporting_period": ["in", period_names]},
        fields=["report", "reporting_period", "review_status", "review_role", "review_round", "reviewer"], limit_page_length=0)
    from velora_governance.governance.services.reporting_dashboard import build_reporting_dashboard
    return build_reporting_dashboard(periods, assessments, tasks, reports, reviews, framework_by_disclosure)


if frappe is not None:
    get_sustainability_reporting_dashboard = frappe.whitelist()(get_sustainability_reporting_dashboard)


def get_sustainability_report_review_queue(reviewer=None, review_status=None, report=None, governance_entity=None):
    """Return the permission-aware review queue. All query filters are optional."""
    if frappe is None:
        raise RuntimeError("Velora framework runtime is required")
    filters = {}
    if reviewer: filters["reviewer"] = reviewer
    if review_status: filters["review_status"] = review_status
    if report: filters["report"] = report
    if governance_entity:
        if not frappe.has_permission("Governance Entity", "read", governance_entity):
            frappe.throw("Permission denied for governance entity", frappe.PermissionError)
        report_names = frappe.get_list("Sustainability Report", filters={"governance_entity": governance_entity}, fields=["name"])
        filters["report"] = ["in", [r.name for r in report_names]]
    rows = frappe.get_list("Sustainability Report Review", filters=filters,
        fields=["name", "report", "reporting_period", "review_round", "reviewer", "review_role", "review_status", "review_date", "comments", "issues_identified"],
        limit_page_length=0)
    from velora_governance.governance.services.report_review_operations import review_queue
    return review_queue(rows, reviewer=reviewer, status=review_status, report=report)


def create_sustainability_report_review(payload):
    """Create a review assignment after permission and payload validation."""
    if frappe is None: raise RuntimeError("Velora framework runtime is required")
    from velora_governance.governance.services.report_review_operations import validate_review_payload
    values = validate_review_payload(payload or {})
    report = values.get("report")
    if not frappe.has_permission("Sustainability Report", "write", report):
        frappe.throw("You do not have permission to assign a review for this report", frappe.PermissionError)
    doc = frappe.get_doc({"doctype": "Sustainability Report Review", **values})
    doc.insert(ignore_permissions=False)
    return doc.name


def create_sustainability_report_review_issue(payload):
    """Create an issue against a report/review, permission checked at report scope."""
    if frappe is None: raise RuntimeError("Velora framework runtime is required")
    from velora_governance.governance.services.report_review_operations import validate_issue_payload
    values = validate_issue_payload(payload or {})
    if not frappe.has_permission("Sustainability Report", "write", values.get("report")):
        frappe.throw("You do not have permission to create issues for this report", frappe.PermissionError)
    doc = frappe.get_doc({"doctype": "Sustainability Report Review Issue", **values})
    doc.insert(ignore_permissions=False)
    return doc.name


def resolve_sustainability_report_review_issue(issue_name, resolution, status="Resolved"):
    """Update an issue through the framework document lifecycle."""
    if frappe is None: raise RuntimeError("Velora framework runtime is required")
    if status not in ("Resolved", "Closed"): raise ValueError("Resolution status must be Resolved or Closed")
    issue = frappe.get_doc("Sustainability Report Review Issue", issue_name)
    if not frappe.has_permission("Sustainability Report", "write", issue.report):
        frappe.throw("Permission denied for report issue", frappe.PermissionError)
    issue.issue_status = status
    issue.resolution = resolution
    issue.resolved_date = frappe.utils.today()
    issue.save(ignore_permissions=False)
    return issue.name


def assemble_sustainability_report_html(report_name, include_review_notes=False):
    """Assemble a print-friendly escaped HTML report from persisted sections."""
    if frappe is None: raise RuntimeError("Velora framework runtime is required")
    report = frappe.get_doc("Sustainability Report", report_name)
    report.check_permission("read")
    sections = frappe.get_list("Sustainability Report Section", filters={"parent": report_name},
        fields=["sequence", "section_title", "content", "section_status", "framework", "disclosure"],
        order_by="sequence asc", limit_page_length=0)
    reviews = []
    if include_review_notes:
        if not frappe.has_permission("Sustainability Report", "write", report_name):
            frappe.throw("Review notes require report write permission", frappe.PermissionError)
        reviews = frappe.get_list("Sustainability Report Review", filters={"report": report_name},
            fields=["reviewer", "review_status", "comments"], limit_page_length=0)
    from velora_governance.governance.services.report_review_operations import assemble_report_html
    return assemble_report_html(report=report.as_dict(), sections=sections, reviews=reviews,
        include_review_notes=bool(include_review_notes))



def assemble_board_sustainability_report_html(report_name, include_draft_watermark=True):
    """Build a board-ready report HTML from the permission-checked report and child sections."""
    if frappe is None: raise RuntimeError("Velora framework runtime is required")
    report = frappe.get_doc("Sustainability Report", report_name)
    report.check_permission("read")
    sections = frappe.get_list("Sustainability Report Section", filters={"parent": report_name},
        fields=["sequence", "section_title", "content", "section_status", "framework", "standard", "disclosure", "evidence_reference"],
        order_by="sequence asc", limit_page_length=0)
    report_dict = report.as_dict()
    entity = report.get("governance_entity")
    period_label = report.get("reporting_period")
    period_rows = frappe.get_list("Sustainability Reporting Period",
        filters={"governance_entity": entity, "period_name": period_label},
        fields=["name"], limit_page_length=0)
    period_names = [p.get("name") for p in period_rows]
    targets = frappe.get_list("Sustainability Target", filters={"governance_entity": entity},
        fields=["target_title", "baseline_value", "baseline_year", "target_value", "target_year", "current_value", "progress_percent", "target_status", "unit"], limit_page_length=0)
    ghg = frappe.get_list("GHG Calculation", filters={"governance_entity": entity, "reporting_period": ["in", period_names]},
        fields=["reporting_period", "emission_source", "activity_quantity", "unit", "emissions_kgco2e", "emissions_tco2e", "methodology", "data_quality"], limit_page_length=0) if period_names else []
    source_names = list({g.get("emission_source") for g in ghg if g.get("emission_source")})
    source_meta = frappe.get_list("Emission Source", filters={"name": ["in", source_names]},
        fields=["name", "scope", "source_category", "source_name"], limit_page_length=0) if source_names else []
    source_by_name = {x.get("name"): x for x in source_meta}
    ghg_rows = [{"scope": source_by_name.get(g.get("emission_source"), {}).get("scope"),
        "category": source_by_name.get(g.get("emission_source"), {}).get("source_category"),
        "activity": source_by_name.get(g.get("emission_source"), {}).get("source_name") or g.get("emission_source"),
        "quantity": g.get("activity_quantity"), "unit": g.get("unit"),
        "tco2e": g.get("emissions_tco2e")} for g in ghg]
    target_rows = [{"target": t.get("target_title"), "baseline": f"{t.get('baseline_value')} ({t.get('baseline_year')})",
        "target_value": f"{t.get('target_value')} ({t.get('target_year')})", "current_value": t.get("current_value"),
        "progress_percent": t.get("progress_percent"), "status": t.get("target_status")} for t in targets]
    assessments = frappe.get_list("Materiality Assessment", filters={"governance_entity": entity, "reporting_period": ["in", period_names]},
        fields=["name", "overall_summary", "assessment_status"], limit_page_length=0) if period_names else []
    materiality_rows = []
    for assessment in assessments:
        materiality_rows.extend(frappe.get_list("Materiality Topic", filters={"parent": assessment.get("name")},
            fields=["topic", "impact_score", "financial_score", "materiality_score", "material", "rationale", "topic_owner", "evidence_reference"], limit_page_length=0))
    materiality_report_rows = [{"topic": r.get("topic"), "impact_score": r.get("impact_score"),
        "financial_score": r.get("financial_score"), "materiality": r.get("materiality_score"),
        "priority": "Material" if r.get("material") else "Not Material"} for r in materiality_rows]
    disclosure_assessments = frappe.get_list("Sustainability Disclosure Assessment", filters={"reporting_period": ["in", period_names]},
        fields=["disclosure", "assessment_status", "readiness_percent", "gap_summary"], limit_page_length=0) if period_names else []
    disclosure_names = [d.get("disclosure") for d in disclosure_assessments if d.get("disclosure")]
    disclosure_meta = frappe.get_list("Sustainability Disclosure", filters={"name": ["in", disclosure_names]},
        fields=["name", "framework", "disclosure_code", "disclosure_title"], limit_page_length=0) if disclosure_names else []
    meta_by_name = {d.get("name"): d for d in disclosure_meta}
    disclosure_rows = [{"framework": meta_by_name.get(d.get("disclosure"), {}).get("framework"),
        "disclosure_code": meta_by_name.get(d.get("disclosure"), {}).get("disclosure_code"),
        "disclosure": meta_by_name.get(d.get("disclosure"), {}).get("disclosure_title") or d.get("disclosure"),
        "status": d.get("assessment_status"), "readiness_percent": d.get("readiness_percent")} for d in disclosure_assessments]
    evidence = frappe.get_list("Sustainability Evidence", filters={"governance_entity": entity, "reporting_period": ["in", period_names]},
        fields=["document_reference", "description", "source", "evidence_date"], limit_page_length=0) if period_names else []
    from velora_governance.governance.services.report_publishing import assemble_board_report_html
    return assemble_board_report_html(report=report_dict, sections=sections, targets=target_rows, emissions=ghg_rows,
        materiality=materiality_report_rows, disclosures=disclosure_rows,
        evidence_references=[{"reference": e.get("document_reference"), "description": e.get("description"),
            "source": e.get("source"), "date": e.get("evidence_date")} for e in evidence],
        include_draft_watermark=bool(include_draft_watermark))


def create_sustainability_report_publication(report_name, payload):
    """Prepare a publication register entry after finalisation/review completeness checks."""
    if frappe is None: raise RuntimeError("Velora framework runtime is required")
    report = frappe.get_doc("Sustainability Report", report_name)
    report.check_permission("write")
    sections = frappe.get_list("Sustainability Report Section", filters={"parent": report_name},
        fields=["section_status", "content"], limit_page_length=0)
    issues = frappe.get_list("Sustainability Report Review Issue", filters={"report": report_name, "issue_status": ["not in", ["Resolved", "Closed"]]},
        fields=["name"], limit_page_length=0)
    reviews = frappe.get_list("Sustainability Report Review", filters={"report": report_name, "review_status": "Completed"},
        fields=["name"], limit_page_length=0)
    from velora_governance.governance.services.report_publishing import validate_publication_payload, assemble_board_report_html, publication_digest
    values = validate_publication_payload(payload or {}, report=report.as_dict(), sections=sections,
        open_issue_count=len(issues), approved_review_count=len(reviews))
    if not values["eligible"]:
        return {"eligible": False, "blockers": values["blockers"]}
    content = assemble_board_sustainability_report_html(report_name, include_draft_watermark=False)
    revision = int(report.get("current_revision") or 1)
    doc = frappe.get_doc({"doctype": "Sustainability Report Publication", "report": report_name,
        "governance_entity": report.get("governance_entity"), "reporting_period": report.get("reporting_period"),
        "revision_number": revision, "publication_date": values["publication_date"],
        "publication_channel": values["publication_channel"], "audience": values["audience"],
        "publication_url": values.get("publication_url"), "file_reference": values.get("file_reference"),
        "content_sha256": publication_digest(content), "publication_status": "Prepared",
        "published_by": frappe.session.user, "notes": values.get("notes")})
    doc.insert(ignore_permissions=False)
    return {"eligible": True, "publication": doc.name, "publication_status": doc.publication_status,
        "content_sha256": doc.content_sha256, "publication_date": doc.publication_date}


def mark_sustainability_report_publication_published(publication_name):
    """Mark a prepared publication as released; report approval remains workflow-controlled."""
    if frappe is None: raise RuntimeError("Velora framework runtime is required")
    publication = frappe.get_doc("Sustainability Report Publication", publication_name)
    publication.check_permission("write")
    report = frappe.get_doc("Sustainability Report", publication.report)
    report.check_permission("read")
    if report.report_status not in ("Finalized", "Published"):
        frappe.throw("The report must be finalized before publication", frappe.ValidationError)
    if publication.publication_status == "Withdrawn":
        frappe.throw("Withdrawn publication cannot be released", frappe.ValidationError)
    publication.publication_status = "Published"
    publication.published_by = frappe.session.user
    publication.publication_date = publication.publication_date or frappe.utils.today()
    publication.save(ignore_permissions=False)
    return publication.name


def add_sustainability_report_distribution(publication_name, payload):
    """Append an auditable distribution entry to a publication register."""
    if frappe is None: raise RuntimeError("Velora framework runtime is required")
    values = payload or {}
    if not str(values.get("recipient") or "").strip():
        frappe.throw("Recipient is required", frappe.ValidationError)
    method = values.get("delivery_method")
    if method not in ("Portal", "Email", "Secure Link", "Physical Copy", "Regulatory Portal", "Other"):
        frappe.throw("A valid delivery method is required", frappe.ValidationError)
    publication = frappe.get_doc("Sustainability Report Publication", publication_name)
    publication.check_permission("write")
    if publication.publication_status != "Published":
        frappe.throw("Distribution can only be logged against a published report", frappe.ValidationError)
    publication.append("distribution", {"recipient": values.get("recipient"),
        "recipient_type": values.get("recipient_type") or "Other", "delivery_method": method,
        "delivery_date": values.get("delivery_date") or frappe.utils.today(),
        "delivery_status": values.get("delivery_status") or "Sent",
        "acknowledged_date": values.get("acknowledged_date"), "notes": values.get("notes") or ""})
    publication.save(ignore_permissions=False)
    return publication.name

def create_sustainability_report_revision(report_name, change_summary):
    """Create an immutable JSON snapshot revision of a report and its sections."""
    if frappe is None: raise RuntimeError("Velora framework runtime is required")
    if not str(change_summary or "").strip(): raise ValueError("Change summary is required")
    report = frappe.get_doc("Sustainability Report", report_name)
    report.check_permission("write")
    sections = frappe.get_list("Sustainability Report Section", filters={"parent": report_name},
        fields=["sequence", "section_title", "framework", "standard", "disclosure", "content", "data_point", "section_status", "evidence_reference", "notes"],
        order_by="sequence asc", limit_page_length=0)
    revisions = frappe.get_list("Sustainability Report Revision", filters={"report": report_name},
        fields=["revision_number"], limit_page_length=0)
    from velora_governance.governance.services.report_review_operations import next_revision_number
    number = next_revision_number(revisions)
    snapshot = {"report": report.as_dict(), "sections": sections, "revision_number": number}
    doc = frappe.get_doc({"doctype": "Sustainability Report Revision", "report": report_name,
        "revision_number": number, "revision_date": frappe.utils.now_datetime(),
        "revision_author": frappe.session.user, "change_summary": change_summary,
        "snapshot_json": frappe.as_json(snapshot), "revision_status": "Draft"})
    doc.insert(ignore_permissions=False)
    report.current_revision = number
    report.save(ignore_permissions=False)
    return {"revision": doc.name, "revision_number": number}


if frappe is not None:
    for _api_name in ("get_sustainability_report_review_queue", "create_sustainability_report_review",
        "create_sustainability_report_review_issue", "resolve_sustainability_report_review_issue",
        "assemble_sustainability_report_html", "create_sustainability_report_revision",
        "assemble_board_sustainability_report_html", "create_sustainability_report_publication",
        "mark_sustainability_report_publication_published",
        "add_sustainability_report_distribution"):

        globals()[_api_name] = frappe.whitelist()(globals()[_api_name])


def export_sustainability_report_document(report_name, export_format="PDF", publication_name=None, export_options=None, template_name=None, revision_name=None):
    """Generate and attach a native PDF or Word report using the permission-aware report assembler."""
    if frappe is None: raise RuntimeError("Velora framework runtime is required")
    report = frappe.get_doc("Sustainability Report", report_name); report.check_permission("read")
    fmt = str(export_format or "PDF").upper()
    if fmt not in ("PDF", "DOCX", "WORD"):
        frappe.throw("Export format must be PDF or DOCX", frappe.ValidationError)
    from velora_governance.governance.services.report_export import render_pdf, render_docx, normalize_export_config
    template_values = {}
    if template_name:
        template = frappe.get_doc("Sustainability Report Export Template", template_name); template.check_permission("read")
        if not template.is_active: frappe.throw("Export template is inactive", frappe.ValidationError)
        template_values = template.as_dict()
    template_values.update({"title": report.get("report_title") or report_name, "entity": report.get("governance_entity"), "period": report.get("reporting_period")})
    allowed_formats = template_values.get("export_formats")
    if allowed_formats and fmt not in [str(x).upper() for x in (allowed_formats if isinstance(allowed_formats, (list,tuple)) else str(allowed_formats).splitlines())]:
        frappe.throw("Selected export format is not enabled on this template", frappe.ValidationError)
    options = normalize_export_config(template_values, export_options or {})
    selected_revision=int(report.get("current_revision") or 1)
    if revision_name:
        revision=frappe.get_doc("Sustainability Report Revision",revision_name); revision.check_permission("read")
        if revision.report!=report_name: frappe.throw("Revision does not belong to selected report",frappe.ValidationError)
        import json
        snapshot=json.loads(revision.snapshot_json or "{}")
        from velora_governance.governance.services.report_publishing import assemble_board_report_html
        html_content=assemble_board_report_html(report=snapshot.get("report") or {},sections=snapshot.get("sections") or [],include_draft_watermark=False)
        selected_revision=int(revision.revision_number or 1)
    else:
        html_content = assemble_board_sustainability_report_html(report_name, include_draft_watermark=False)
    content = render_pdf(html_content, options) if fmt == "PDF" else render_docx(html_content, options)
    extension = "pdf" if fmt == "PDF" else "docx"
    safe_name = __import__("re").sub(r"[^A-Za-z0-9._-]+", "_", str(report_name)).strip("._") or "report"
    filename = f"{safe_name}-r{int(report.get('current_revision') or 1)}.{extension}"
    file_doc = _save_private_file(filename, content, "Sustainability Report", report_name)
    if publication_name:
        publication = frappe.get_doc("Sustainability Report Publication", publication_name)
        if not frappe.has_permission("Sustainability Report Publication", "write"):
            frappe.throw("You do not have permission to update this publication", frappe.PermissionError)
        if publication.report != report_name:
            frappe.throw("Publication does not belong to the selected report", frappe.ValidationError)
        if int(publication.revision_number or 1)!=selected_revision:
            frappe.throw("Exported revision does not match the publication register revision", frappe.ValidationError)
        publication.file_reference = file_doc.file_url
        publication.save(ignore_permissions=False)
    return {"file": file_doc.name, "file_url": file_doc.file_url, "filename": filename,
            "format": fmt, "bytes": len(content), "revision": selected_revision}


def preview_sustainability_report_export(report_name, template_name=None, export_options=None, revision_name=None):
    """Return report HTML preview plus normalized export settings."""
    if frappe is None: raise RuntimeError("Velora framework runtime is required")
    report=frappe.get_doc("Sustainability Report", report_name); report.check_permission("read")
    from velora_governance.governance.services.report_export import normalize_export_config
    values={"title":report.get("report_title") or report_name,"entity":report.get("governance_entity"),"period":report.get("reporting_period")}
    if template_name:
        template=frappe.get_doc("Sustainability Report Export Template",template_name); template.check_permission("read")
        if not template.is_active: frappe.throw("Export template is inactive",frappe.ValidationError)
        values.update(template.as_dict())
    values.update({"title":report.get("report_title") or report_name,"entity":report.get("governance_entity"),"period":report.get("reporting_period")})
    options=normalize_export_config(values,export_options or {})
    selected_revision=int(report.get("current_revision") or 1)
    if revision_name:
        revision=frappe.get_doc("Sustainability Report Revision",revision_name); revision.check_permission("read")
        if revision.report!=report_name: frappe.throw("Revision does not belong to selected report",frappe.ValidationError)
        import json
        snapshot=json.loads(revision.snapshot_json or "{}")
        from velora_governance.governance.services.report_publishing import assemble_board_report_html
        html_content=assemble_board_report_html(report=snapshot.get("report") or {},sections=snapshot.get("sections") or [],include_draft_watermark=True)
        selected_revision=int(revision.revision_number or 1)
    else:
        html_content=assemble_board_sustainability_report_html(report_name,include_draft_watermark=True)
    return {"html_preview":html_content,"export_options":options,"report":report_name,"revision":selected_revision}


def acknowledge_sustainability_report_distribution(publication_name, distribution_row_name, acknowledged_date=None, notes=None):
    """Update distribution acknowledgment on an authorized published report record."""
    if frappe is None: raise RuntimeError("Velora framework runtime is required")
    publication=frappe.get_doc("Sustainability Report Publication",publication_name); publication.check_permission("write")
    if publication.publication_status!="Published": frappe.throw("Acknowledgment requires a published report",frappe.ValidationError)
    row=next((d for d in publication.distribution if d.name==distribution_row_name),None)
    if not row: frappe.throw("Distribution entry not found",frappe.DoesNotExistError)
    row.acknowledged_date=acknowledged_date or frappe.utils.today()
    if notes: row.notes=(row.notes or "")+"\n"+str(notes)
    publication.save(ignore_permissions=False)
    return {"publication":publication.name,"distribution":row.name,"acknowledged_date":row.acknowledged_date}


def compare_sustainability_report_revision(report_name, revision_name):
    """Compare an accessible immutable report snapshot with the current assembled report."""
    if frappe is None: raise RuntimeError("Velora framework runtime is required")
    report=frappe.get_doc("Sustainability Report", report_name); report.check_permission("read")
    revision=frappe.get_doc("Sustainability Report Revision", revision_name); revision.check_permission("read")
    if revision.report != report_name:
        frappe.throw("Revision does not belong to the selected report", frappe.ValidationError)
    import json
    snapshot=json.loads(revision.snapshot_json or "{}")
    old_report=snapshot.get("report") or {}; old_sections=snapshot.get("sections") or []
    from velora_governance.governance.services.report_publishing import assemble_board_report_html
    old_html=assemble_board_report_html(report=old_report, sections=old_sections, include_draft_watermark=False)
    new_html=assemble_board_sustainability_report_html(report_name, include_draft_watermark=False)
    from velora_governance.governance.services.report_export import compare_revisions
    result=compare_revisions(old_html,new_html)
    result.update({"revision":revision.name,"revision_number":revision.revision_number,"report":report_name})
    return result


if frappe is not None:
    for _api_name in ("export_sustainability_report_document", "preview_sustainability_report_export", "acknowledge_sustainability_report_distribution", "compare_sustainability_report_revision"):
        globals()[_api_name] = frappe.whitelist()(globals()[_api_name])


def get_governance_automation_execution_history(status=None, limit=50, offset=0):
    """Permission-aware automation history for Governance operations UI."""
    if frappe is None:
        raise RuntimeError("Velora framework runtime is required")
    if not frappe.has_permission("Governance Automation Execution", "read"):
        frappe.throw("You do not have permission to view governance automation history", frappe.PermissionError)
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    filters = {"execution_status": status} if status else {}
    return frappe.get_list("Governance Automation Execution", filters=filters,
        fields=["name", "idempotency_key", "correlation_id", "action_type", "execution_status",
                "attempts", "actor", "last_error", "next_retry_at", "started_at", "completed_at"],
        order_by="modified desc", limit_page_length=limit, limit_start=offset)


def get_governance_automation_execution_history_page(status=None, limit=50, offset=0):
    """Permission-aware paged execution history with a stable total count."""
    if frappe is None:
        raise RuntimeError("Velora framework runtime is required")
    if not frappe.has_permission("Governance Automation Execution", "read"):
        frappe.throw("You do not have permission to view governance automation history", frappe.PermissionError)
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    filters = {"execution_status": status} if status else {}
    total = frappe.get_count("Governance Automation Execution", filters=filters)
    rows = frappe.get_list("Governance Automation Execution", filters=filters,
        fields=["name", "idempotency_key", "correlation_id", "action_type", "execution_status",
                "attempts", "actor", "last_error", "next_retry_at", "started_at", "completed_at"],
        order_by="modified desc", limit_page_length=limit, limit_start=offset)
    return {"rows": rows, "total": total, "limit": limit, "offset": offset,
            "has_more": offset + len(rows) < total}


def retry_governance_automation_execution(name):
    """Permission-checked manual retry for a failed governance automation record."""
    if frappe is None:
        raise RuntimeError("Velora framework runtime is required")
    if not frappe.has_permission("Governance Automation Execution", "write", name):
        frappe.throw("You do not have permission to retry this execution", frappe.PermissionError)
    doc = frappe.get_doc("Governance Automation Execution", name)
    doc.check_permission("write")
    if doc.execution_status not in ("Failed", "Retry Pending"):
        frappe.throw("Only failed or retry-pending executions can be retried")
    if int(doc.attempts or 0) >= 5:
        frappe.throw("Maximum attempts reached; create a new action or review the failure")
    doc.execution_status = "Retry Pending"
    doc.next_retry_at = frappe.utils.now_datetime()
    doc.last_error = ""
    doc.save(ignore_permissions=False)
    return {"name": doc.name, "status": doc.execution_status, "next_retry_at": doc.next_retry_at}


if frappe is not None:
    get_governance_automation_execution_history = frappe.whitelist()(get_governance_automation_execution_history)
    get_governance_automation_execution_history_page = frappe.whitelist()(get_governance_automation_execution_history_page)
    retry_governance_automation_execution = frappe.whitelist()(retry_governance_automation_execution)


def get_governance_automation_configuration():
    """Return normalized automation settings to authorized administrators only."""
    if frappe is None:
        raise RuntimeError("Velora framework runtime is required")
    if not frappe.has_permission("Governance Automation Configuration", "read"):
        frappe.throw("You do not have permission to view automation configuration", frappe.PermissionError)
    from velora_governance.governance.services.governance_automation_configuration import load_configuration
    return load_configuration()


def save_governance_automation_configuration(payload):
    """Validate and save native configuration. Permission check is enforced server-side."""
    if frappe is None:
        raise RuntimeError("Velora framework runtime is required")
    if not frappe.has_permission("Governance Automation Configuration", "write"):
        frappe.throw("You do not have permission to change automation configuration", frappe.PermissionError)
    from velora_governance.governance.services.governance_automation_configuration import validate_configuration
    values = payload or {}
    result = validate_configuration(values)
    if not result["valid"]:
        frappe.throw("Invalid automation configuration: " + "; ".join(result["errors"]))
    normalized = result["normalized"]
    doc = frappe.get_doc("Governance Automation Configuration", "GAC")
    doc.automation_enabled = normalized["automation_enabled"]
    doc.reminder_days_before = ",".join(map(str, normalized["reminder_days_before"]))
    doc.escalation_days_overdue = ",".join(map(str, normalized["escalation_days_overdue"]))
    doc.terminal_statuses = ",".join(normalized["terminal_statuses"])
    doc.max_attempts = normalized["max_attempts"]
    doc.max_batch_size = normalized["max_batch_size"]
    doc.retry_base_minutes = normalized["retry_base_minutes"]
    doc.retry_max_hours = normalized["retry_max_hours"]
    doc.owner_field_mapping = __import__("json").dumps(normalized["owner_field_mapping"], sort_keys=True)
    doc.recipient_overrides = __import__("json").dumps(normalized["recipient_overrides"], sort_keys=True)
    doc.save(ignore_permissions=False)
    return normalized


if frappe is not None:
    get_governance_automation_configuration = frappe.whitelist()(get_governance_automation_configuration)
    save_governance_automation_configuration = frappe.whitelist()(save_governance_automation_configuration)


def upsert_governance_exception(payload):
    """Permission-checked idempotent exception create/update from allowlisted source."""
    if frappe is None:
        raise RuntimeError("Velora framework runtime is required")
    if not frappe.has_permission("Governance Exception", "create") or not frappe.has_permission("Governance Exception", "write"):
        frappe.throw("You do not have permission to create or update governance exceptions", frappe.PermissionError)
    from velora_governance.governance.services.governance_exception_persistence import upsert_exception
    configuration=get_governance_exception_configuration()
    result = upsert_exception(payload or {}, frappe_api=frappe, configuration=configuration)
    from velora_governance.governance.services.governance_exception_activity import append_activity
    append_activity(result["name"], "Created" if result.get("created") else "Source Updated",
        actor=frappe.session.user, details="Exception detected or source-derived details refreshed",
        source_key="upsert:" + str(result.get("created")), api=frappe)
    return result


def get_governance_exception_centre(status=None, severity=None, assigned_to=None, limit=50, offset=0):
    """Permission-aware exception centre data and KPIs."""
    if frappe is None:
        raise RuntimeError("Velora framework runtime is required")
    if not frappe.has_permission("Governance Exception", "read"):
        frappe.throw("You do not have permission to view governance exceptions", frappe.PermissionError)
    limit = max(1, min(int(limit or 50), 200)); offset = max(0, int(offset or 0))
    filters = {}
    if status: filters["status"] = status
    if severity: filters["severity"] = severity
    # Owner filter is native and permission-aware through frappe.get_list.
    if assigned_to: filters["assigned_to"] = assigned_to
    total = frappe.get_count("Governance Exception", filters=filters)
    rows = frappe.get_list("Governance Exception", filters=filters,
        fields=["name", "source_doctype", "source_name", "exception_type", "title", "due_date",
                "overdue_days", "risk_score", "severity", "status", "assigned_to", "route", "routing_status", "modified"],
        order_by="severity desc, overdue_days desc, modified desc", limit_page_length=limit, limit_start=offset)
    all_rows = frappe.get_list("Governance Exception", fields=["status", "severity", "overdue_days"], limit_page_length=10000)
    active_statuses = {"Open", "Assigned", "In Progress", "Escalated", "Pending Evidence"}
    return {"rows": rows, "total": total, "limit": limit, "offset": offset, "has_more": offset + len(rows) < total,
        "kpis": {"total": len(all_rows), "active": sum(r.get("status") in active_statuses for r in all_rows),
        "overdue_active": sum((r.get("overdue_days") or 0) > 0 and r.get("status") in active_statuses for r in all_rows),
        "critical_active": sum(r.get("severity") == "Critical" and r.get("status") in active_statuses for r in all_rows)}}


def assign_governance_exception(name, user):
    if frappe is None: raise RuntimeError("Velora framework runtime is required")
    if not frappe.has_permission("Governance Exception", "write", name):
        frappe.throw("You do not have permission to assign this exception", frappe.PermissionError)
    doc = frappe.get_doc("Governance Exception", name); doc.check_permission("write")
    previous = doc.assigned_to
    user_doc = frappe.get_doc("User", user)
    if user_doc.enabled != 1: frappe.throw("Assignment target must be an enabled User")
    doc.assigned_to = user; doc.status = "Assigned" if doc.status == "Open" else doc.status
    doc.save(ignore_permissions=False)
    from velora_governance.governance.services.governance_exception_activity import append_activity
    append_activity(doc.name, "Reassigned" if previous else "Assigned", actor=frappe.session.user,
        details=f"Assigned from {previous or 'Unassigned'} to {user}", api=frappe)
    return {"name": doc.name, "assigned_to": user, "status": doc.status}


def transition_governance_exception(name, target, evidence=None):
    if frappe is None: raise RuntimeError("Velora framework runtime is required")
    if not frappe.has_permission("Governance Exception", "write", name):
        frappe.throw("You do not have permission to update this exception", frappe.PermissionError)
    doc = frappe.get_doc("Governance Exception", name); doc.check_permission("write")
    from velora_governance.governance.services.governance_exception_persistence import transition_persisted_exception
    configuration=get_governance_exception_configuration()
    try:
        previous_status = doc.status
        result = transition_persisted_exception(doc, target, actor=frappe.session.user, evidence=evidence,
            evidence_required=configuration.get("evidence_required",True), now=frappe.utils.now_datetime())
        from velora_governance.governance.services.governance_exception_activity import append_activity
        append_activity(doc.name, "Status Changed", actor=frappe.session.user,
            details=f"Status changed from {previous_status} to {target}", evidence_reference=evidence,
            source_key=f"transition:{previous_status}:{target}:{frappe.utils.now_datetime()}", api=frappe)
        return result
    except ValueError as exc:
        frappe.throw(str(exc), frappe.ValidationError)


if frappe is not None:
    for _api_name in ("upsert_governance_exception", "get_governance_exception_centre",
                       "assign_governance_exception", "transition_governance_exception"):
        globals()[_api_name] = frappe.whitelist()(globals()[_api_name])


def get_governance_exception_configuration():
    if frappe is None: raise RuntimeError("Velora framework runtime is required")
    if not frappe.has_permission("Governance Exception Configuration", "read"):
        frappe.throw("Permission denied", frappe.PermissionError)
    from velora_governance.governance.services.governance_exception_configuration import DEFAULTS
    try:
        doc = frappe.get_single("Governance Exception Configuration")
        return {"low_days":doc.low_days,"medium_days":doc.medium_days,"high_days":doc.high_days,"critical_days":doc.critical_days,
            "low_score":doc.low_score,"medium_score":doc.medium_score,"high_score":doc.high_score,"critical_score":doc.critical_score,
            "routes":{"Low":doc.route_low,"Medium":doc.route_medium,"High":doc.route_high,"Critical":doc.route_critical},
            "evidence_required":bool(doc.evidence_required),
            "escalation_after_hours":doc.escalation_after_hours or "24,72,168",
            "escalation_targets":__import__("json").loads(doc.escalation_targets or "{}") if isinstance(doc.escalation_targets,str) else (doc.escalation_targets or {})}
    except Exception:
        return dict(DEFAULTS)


def save_governance_exception_configuration(payload):
    if frappe is None: raise RuntimeError("Velora framework runtime is required")
    if not frappe.has_permission("Governance Exception Configuration", "write"):
        frappe.throw("Only authorized administrators may configure exceptions", frappe.PermissionError)
    from velora_governance.governance.services.governance_exception_configuration import validate_exception_configuration
    result=validate_exception_configuration(payload or {})
    if not result["valid"]: frappe.throw("; ".join(result["errors"]), frappe.ValidationError)
    c=result["normalized"]; routes=c["routes"]
    doc=frappe.get_single("Governance Exception Configuration")
    for field in ("low_days","medium_days","high_days","critical_days","low_score","medium_score","high_score","critical_score","evidence_required"):
        setattr(doc,field,c[field])
    doc.route_low=routes["Low"]; doc.route_medium=routes["Medium"]; doc.route_high=routes["High"]; doc.route_critical=routes["Critical"]
    doc.escalation_after_hours=c["escalation_after_hours"]
    doc.escalation_targets=__import__("json").dumps(c["escalation_targets"],sort_keys=True)
    doc.save(ignore_permissions=False)
    return {"saved":True,"configuration":c}


def bulk_assign_governance_exceptions(exception_names, user):
    if frappe is None: raise RuntimeError("Velora framework runtime is required")
    from velora_governance.governance.services.governance_exception_configuration import validate_bulk_assignment
    validation=validate_bulk_assignment(exception_names,user)
    if not validation["valid"]: frappe.throw(validation["reason"],frappe.ValidationError)
    target=frappe.get_doc("User",validation["user"])
    if not target.enabled: frappe.throw("Assignment target must be enabled")
    assigned=[]; failed=[]
    for name in validation["names"]:
        try:
            if not frappe.has_permission("Governance Exception","write",name):
                failed.append({"name":name,"reason":"permission_denied"}); continue
            doc=frappe.get_doc("Governance Exception",name); doc.check_permission("write")
            if doc.status in ("Resolved","Closed"):
                failed.append({"name":name,"reason":"terminal_exception"}); continue
            previous=doc.assigned_to
            doc.assigned_to=validation["user"]
            if doc.status=="Open": doc.status="Assigned"
            doc.save(ignore_permissions=False)
            from velora_governance.governance.services.governance_exception_activity import append_activity
            append_activity(doc.name, "Reassigned" if previous else "Assigned", actor=frappe.session.user,
                details=f"Bulk assignment changed from {previous or 'Unassigned'} to {validation['user']}", api=frappe)
            frappe.get_doc({"doctype":"Comment","comment_type":"Comment","reference_doctype":"Governance Exception","reference_name":name,
                "content":f"Bulk assignment changed from {previous or 'Unassigned'} to {validation['user']} by {frappe.session.user}"}).insert(ignore_permissions=True)
            assigned.append(name)
        except Exception as exc:
            failed.append({"name":name,"reason":str(exc)[:250]})
    return {"assigned":assigned,"failed":failed,"count":len(assigned)}


def get_governance_exception_timeline(name, limit=100):
    if frappe is None: raise RuntimeError("Velora framework runtime is required")
    if not frappe.has_permission("Governance Exception", "read", name):
        frappe.throw("Permission denied", frappe.PermissionError)
    limit=max(1,min(int(limit or 100),250))
    return frappe.get_list("Governance Exception Activity", filters={"exception":name},
        fields=["name","activity_type","actor","details","evidence_reference","activity_datetime"],
        order_by="activity_datetime desc", limit_page_length=limit)


def add_governance_exception_activity(name, details, evidence_reference=None, activity_type="Comment"):
    if frappe is None: raise RuntimeError("Velora framework runtime is required")
    if not frappe.has_permission("Governance Exception", "write", name):
        frappe.throw("Permission denied", frappe.PermissionError)
    details=str(details or "").strip()
    if not details: frappe.throw("Activity details are required", frappe.ValidationError)
    allowed={"Comment","Evidence Added"}
    if activity_type not in allowed: frappe.throw("Unsupported activity type", frappe.ValidationError)
    from velora_governance.governance.services.governance_exception_activity import append_activity
    return append_activity(name, activity_type, actor=frappe.session.user, details=details,
        evidence_reference=str(evidence_reference or "").strip() or None, api=frappe)


def get_governance_exception_workload():
    if frappe is None: raise RuntimeError("Velora framework runtime is required")
    if not frappe.has_permission("Governance Exception", "read"):
        frappe.throw("Permission denied", frappe.PermissionError)
    rows=frappe.get_list("Governance Exception", fields=["status","assigned_to","overdue_days","creation"],limit_page_length=10000)
    now=frappe.utils.now_datetime()
    for row in rows:
        created=row.get("creation")
        row["age_days"]=(now-created).days if created else int(row.get("overdue_days") or 0)
    from velora_governance.governance.services.governance_exception_escalation import workload_metrics
    return workload_metrics(rows)


if frappe is not None:
    for _api_name in ("get_governance_exception_configuration","save_governance_exception_configuration","bulk_assign_governance_exceptions","get_governance_exception_timeline","add_governance_exception_activity","get_governance_exception_workload"):
        globals()[_api_name]=frappe.whitelist()(globals()[_api_name])


# Reconciled v10.5 exception analytics APIs
def get_governance_exception_analytics(filters=None):
    """Permission-aware exception analytics; SLA facts are only consumed if provided by the SLA owner."""
    if frappe is None: raise RuntimeError("Velora framework runtime is required")
    if not frappe.has_permission("Governance Exception", "read"):
        frappe.throw("Permission denied", frappe.PermissionError)
    filters = dict(filters or {})
    query_filters = {}
    for field in ("status", "severity", "assigned_to", "source_doctype"):
        if filters.get(field): query_filters[field] = filters[field]
    rows = frappe.get_list("Governance Exception", filters=query_filters,
        fields=["name", "status", "severity", "assigned_to", "due_date", "source_doctype", "source_name", "modified"],
        limit_page_length=10000)
    from velora_governance.governance.services.governance_exception_analytics import build_exception_analytics
    return build_exception_analytics(rows, today=frappe.utils.today())

def get_governance_exception_report(filters=None, limit=5000):
    """Permission-aware exception report; report rows are restricted by native get_list permissions."""
    if frappe is None: raise RuntimeError("Velora framework runtime is required")
    if not frappe.has_permission("Governance Exception", "read"):
        frappe.throw("Permission denied", frappe.PermissionError)
    filters = dict(filters or {})
    query_filters = {}
    for field in ("status", "severity", "assigned_to", "source_doctype"):
        if filters.get(field): query_filters[field] = filters[field]
    limit = max(1, min(int(limit or 5000), 5000))
    rows = frappe.get_list("Governance Exception", filters=query_filters,
        fields=["name", "source_doctype", "source_name", "exception_type", "title", "description", "due_date",
                "overdue_days", "risk_score", "severity", "status", "assigned_to", "route", "routing_status", "modified"],
        order_by="due_date asc, severity desc", limit_page_length=limit)
    from velora_governance.governance.services.governance_exception_analytics import build_exception_report
    return build_exception_report(rows, filters=filters, today=frappe.utils.today())

if frappe is not None:
    for _api_name in ("get_governance_exception_analytics", "get_governance_exception_report"):
        globals()[_api_name] = frappe.whitelist()(globals()[_api_name])


# Advanced Governance Report Centre (permission-aware native list queries)
def get_governance_report_catalog():
    if frappe is None: raise RuntimeError("Velora framework runtime is required")
    from velora_governance.governance.services.governance_report_catalog import report_catalog
    return report_catalog()


def run_governance_report(report_id, filters=None, limit=5000):
    """Run a catalogue report with native permission-aware get_list access."""
    if frappe is None: raise RuntimeError("Velora framework runtime is required")
    from velora_governance.governance.services.governance_report_catalog import get_report_definition, build_report, build_date_filters
    definition=get_report_definition(report_id)
    doctype=definition["doctype"]
    if not frappe.has_permission(doctype, "read"):
        frappe.throw(f"You do not have permission to read {doctype}", frappe.PermissionError)
    filters=dict(filters or {})
    allowed_filter_fields={"governance_entity","board","committee","meeting","assigned_owner","responsible_owner","assigned_to","status","action_status","risk_status","policy_status","filing_status","annual_return_status","assessment_status","report_status","reporting_period","due_date","scheduled_start","scheduled_end","term_end_date","next_review_date","target_year","period_name","severity","priority","task_status"}
    query_filters={}
    for field,value in filters.items():
        if field in allowed_filter_fields and value not in (None,"") and field in definition["fields"]:
            query_filters[field]=value
    selected_field=filters.get("filter_field")
    selected_value=filters.get("filter_value")
    if selected_field in allowed_filter_fields and selected_field in definition["fields"] and selected_value not in (None,""):
        query_filters[selected_field]=selected_value
    date_field=filters.get("date_field")
    date_from=filters.get("date_from")
    date_to=filters.get("date_to")
    query_filters.update(build_date_filters(report_id, date_field, date_from, date_to))
    limit=max(1,min(int(limit or 5000),5000))
    rows=frappe.get_list(doctype, filters=query_filters, fields=definition["fields"],
        order_by="modified desc", limit_page_length=limit)
    return build_report(report_id, rows, filters=query_filters)



def compare_governance_report_periods(report_id, filters=None, comparison_mode="previous_period", limit=5000):
    """Run a permission-aware report for current and comparison periods and calculate deltas."""
    if frappe is None: raise RuntimeError("Velora framework runtime is required")
    from datetime import date, timedelta
    from velora_governance.governance.services.governance_report_catalog import get_report_definition, REPORT_DATE_FIELDS, compare_report_periods
    filters=dict(filters or {})
    date_field=filters.get("date_field")
    start_raw=filters.get("date_from"); end_raw=filters.get("date_to")
    if not date_field or date_field not in REPORT_DATE_FIELDS.get(report_id,[]):
        frappe.throw("Select a supported date field for period comparison", frappe.ValidationError)
    try:
        current_start=date.fromisoformat(str(start_raw)); current_end=date.fromisoformat(str(end_raw))
    except (TypeError,ValueError):
        frappe.throw("Period comparison requires valid From and To dates", frappe.ValidationError)
    if current_start>current_end: frappe.throw("From date cannot be after To date", frappe.ValidationError)
    if comparison_mode not in ("previous_period","year_over_year"):
        frappe.throw("Unsupported comparison mode", frappe.ValidationError)
    if comparison_mode=="previous_period":
        days=(current_end-current_start).days+1
        prior_end=current_start-timedelta(days=1); prior_start=prior_end-timedelta(days=days-1)
    else:
        def subtract_year(d):
            try: return d.replace(year=d.year-1)
            except ValueError: return d.replace(year=d.year-1,day=28)
        prior_start=subtract_year(current_start); prior_end=subtract_year(current_end)
    common={k:v for k,v in filters.items() if k not in ("date_from","date_to","date_field")}
    current_filters={**common,"date_field":date_field,"date_from":current_start.isoformat(),"date_to":current_end.isoformat()}
    prior_filters={**common,"date_field":date_field,"date_from":prior_start.isoformat(),"date_to":prior_end.isoformat()}
    current=run_governance_report(report_id,current_filters,limit)
    prior=run_governance_report(report_id,prior_filters,limit)
    return {"report_id":report_id,"comparison_mode":comparison_mode,"current_period":{"from":current_start.isoformat(),"to":current_end.isoformat(),"report":current},"prior_period":{"from":prior_start.isoformat(),"to":prior_end.isoformat(),"report":prior},"deltas":compare_report_periods(current.get("summary"),prior.get("summary"))}


def export_governance_report_xlsx(report_id, filters=None, comparison_mode="previous_period"):
    """Excel workbook of a permission-aware Governance report, written by the framework's own report exporter.

    The framework exporter is shared with every other report (same layout, print set-up and theme colours) and writes every cell as text or a
    real number, so a record containing "=..." can never run as an Excel formula."""
    import base64
    from datetime import datetime
    from velora.reporting import Column, ReportBuilder
    from velora.reporting.excel import report_to_xlsx
    report = run_governance_report(report_id, filters or {})
    f = dict(filters or {})
    comparison = None
    if f.get("date_field") and f.get("date_from") and f.get("date_to"):
        comparison = compare_governance_report_periods(report_id, f, comparison_mode)
    title = report.get("title") or report_id.replace("_", " ").title()
    cols = report.get("columns", [])
    rb = ReportBuilder(title, [Column(c, c.replace("_", " ").title(), "Data", total="none") for c in cols] or [Column("name", "Name")],
                       subtitle=report.get("description", ""))
    for row in report.get("rows", []):
        rb.row({c: row.get(c) for c in cols})
    summary = [{"label": k.replace("_", " ").title(), "value": v, "fieldtype": "Int" if isinstance(v, int) else "Float"}
               for k, v in (report.get("summary") or {}).items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
    notes = []
    if comparison:
        cp, pp = comparison.get("current_period", {}), comparison.get("prior_period", {})
        notes.append(f"Current period {cp.get('from')} to {cp.get('to')}; prior period {pp.get('from')} to {pp.get('to')} "
                     f"({str(comparison.get('comparison_mode', '')).replace('_', ' ')}).")
        for key, val in (comparison.get("deltas") or {}).items():
            if key != "group_distribution" and isinstance(val, dict):
                notes.append(f"{key.replace('_', ' ').title()}: now {val.get('current')}, before {val.get('prior')}, change {val.get('delta')} ({val.get('percent_change')}%).")
    result = rb.build(filters=[(k, v) for k, v in f.items() if v not in (None, "")], summary=summary, notes=notes)
    data = report_to_xlsx(result, user=frappe.session.user)
    filename = f"{report_id.replace('_', '-')}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.xlsx"
    return {"filename": filename, "content_base64": base64.b64encode(data).decode("ascii"),
            "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


if frappe is not None:
    get_governance_report_catalog=frappe.whitelist()(get_governance_report_catalog)
    run_governance_report=frappe.whitelist()(run_governance_report)
    compare_governance_report_periods=frappe.whitelist()(compare_governance_report_periods)
    export_governance_report_xlsx=frappe.whitelist()(export_governance_report_xlsx)


def get_ghg_inventory(governance_entity, reporting_period, denominators=None):
    """Scope 1/2/3 inventory (location- and market-based Scope 2, Scope 3 by category, biogenic, intensity, base-year change) for one entity and period."""
    if frappe is None:
        raise RuntimeError("Velora framework runtime is required")
    if not frappe.has_permission("Governance Entity", "read", governance_entity):
        frappe.throw("You do not have permission to view this governance entity", frappe.PermissionError)
    from velora_governance.governance.services.ghg_accounting import inventory_for
    return inventory_for(governance_entity, reporting_period, denominators)

if frappe is not None:
    get_ghg_inventory = frappe.whitelist()(get_ghg_inventory)


def _feed_guard(governance_entity):
    if frappe is None:
        raise RuntimeError("Velora framework runtime is required")
    if not frappe.has_permission("Governance Entity", "read", governance_entity) or not frappe.has_permission("GHG Calculation", "create"):
        frappe.throw("You need permission to create GHG Calculations for this entity to use the activity feed", frappe.PermissionError)


def preview_activity_feed(governance_entity, reporting_period):
    """Dry run: what spend would be estimated, excluded or left unmapped for the period. Writes nothing."""
    _feed_guard(governance_entity)
    from velora_governance.governance.services.activity_feed import preview
    return preview(governance_entity, reporting_period)


def run_activity_feed(governance_entity, reporting_period):
    """Create or refresh the period's spend-based GHG Calculations from submitted Purchase Invoices (idempotent)."""
    _feed_guard(governance_entity)
    from velora_governance.governance.services.activity_feed import post
    return post(governance_entity, reporting_period, user=getattr(frappe, "session", None) and getattr(frappe.session, "user", None))

if frappe is not None:
    preview_activity_feed = frappe.whitelist()(preview_activity_feed)
    run_activity_feed = frappe.whitelist()(run_activity_feed)


def generate_issb_checklist(governance_entity, reporting_period):
    """Open one Sustainability Disclosure Assessment per IFRS S1/S2 requirement for the period (idempotent)."""
    if frappe is None:
        raise RuntimeError("Velora framework runtime is required")
    if not frappe.has_permission("Sustainability Disclosure Assessment", "create"):
        frappe.throw("You do not have permission to create disclosure assessments", frappe.PermissionError)
    from velora_governance.governance.services.issb_checklist import generate_checklist
    return generate_checklist(governance_entity, reporting_period)


def get_issb_readiness(governance_entity, reporting_period):
    """IFRS S1/S2 readiness by pillar, with evidence read from the GHG inventory, targets, scenario analysis and materiality."""
    if frappe is None:
        raise RuntimeError("Velora framework runtime is required")
    if not frappe.has_permission("Governance Entity", "read", governance_entity):
        frappe.throw("You do not have permission to view this governance entity", frappe.PermissionError)
    from velora_governance.governance.services.issb_checklist import evaluate
    return evaluate(governance_entity, reporting_period)


def apply_materiality_to_disclosures(materiality_assessment):
    """Set disclosure applicability from a completed, approved materiality assessment."""
    if frappe is None:
        raise RuntimeError("Velora framework runtime is required")
    if not frappe.has_permission("Materiality Assessment", "write", materiality_assessment):
        frappe.throw("You do not have permission to apply this materiality assessment", frappe.PermissionError)
    from velora_governance.governance.services.issb_checklist import apply_materiality
    return apply_materiality(materiality_assessment)

if frappe is not None:
    generate_issb_checklist = frappe.whitelist()(generate_issb_checklist)
    get_issb_readiness = frappe.whitelist()(get_issb_readiness)
    apply_materiality_to_disclosures = frappe.whitelist()(apply_materiality_to_disclosures)


def export_ixbrl(governance_entity, reporting_period, attach_to_report=None):
    """Build the Inline XBRL document of the period's GHG facts. Optionally attach it to a Sustainability Report. Unvalidated: see the module notes."""
    if frappe is None:
        raise RuntimeError("Velora framework runtime is required")
    if not frappe.has_permission("Governance Entity", "read", governance_entity):
        frappe.throw("You do not have permission to view this governance entity", frappe.PermissionError)
    from velora_governance.governance.services.ixbrl_export import build
    out = build(governance_entity, reporting_period)
    if attach_to_report:
        if not frappe.has_permission("Sustainability Report", "write", attach_to_report):
            frappe.throw("You do not have permission to attach to this report", frappe.PermissionError)
        f = _save_private_file(f"ghg-{reporting_period}.xhtml", out["document"].encode("utf-8"), "Sustainability Report", attach_to_report)
        out["file_url"] = f.file_url
    return out

if frappe is not None:
    export_ixbrl = frappe.whitelist()(export_ixbrl)


def _sasb_guard(entity=None, write=False):
    if frappe is None:
        raise RuntimeError("Velora framework runtime is required")
    if entity and not frappe.has_permission("Governance Entity", "read", entity):
        frappe.throw("You do not have permission to view this governance entity", frappe.PermissionError)
    if write and not frappe.has_permission("SASB Metric Response", "create"):
        frappe.throw("You do not have permission to maintain SASB metric responses", frappe.PermissionError)


def get_sasb_template():
    """The Excel template for loading SASB industries and metrics (nothing pre-loaded: the content is licensed). Returned base64-encoded."""
    _sasb_guard()
    import base64
    from velora_governance.governance.services.sasb_catalog import template_workbook
    return {"filename": "sasb-import-template.xlsx", "content_base64": base64.b64encode(template_workbook()).decode("ascii")}


def import_sasb_workbook(content_base64):
    """Load SASB industries and metrics from an Excel workbook sent base64-encoded. Updates by code; never deletes."""
    _sasb_guard(write=True)
    if not frappe.has_permission("SASB Metric", "create"):
        frappe.throw("You do not have permission to import SASB metrics", frappe.PermissionError)
    import base64
    from velora_governance.governance.services.sasb_catalog import import_workbook
    try:
        data = base64.b64decode(content_base64, validate=True)
    except Exception:
        frappe.throw("The file could not be read.")
    if len(data) > 10 * 1024 * 1024:
        frappe.throw("The workbook is larger than 10 MB.")
    return import_workbook(data)


def generate_sasb_responses(governance_entity, reporting_period):
    """Open a response for every active metric of the industries the entity adopted; linked data points fill them. Idempotent."""
    _sasb_guard(governance_entity, write=True)
    from velora_governance.governance.services.sasb_catalog import generate_responses
    return generate_responses(governance_entity, reporting_period)


def get_sasb_summary(governance_entity, reporting_period):
    """Counts of SASB metric responses by status for the period."""
    _sasb_guard(governance_entity)
    from velora_governance.governance.services.sasb_catalog import summary
    return summary(governance_entity, reporting_period)


if frappe is not None:
    get_sasb_template = frappe.whitelist()(get_sasb_template)
    import_sasb_workbook = frappe.whitelist()(import_sasb_workbook)
    generate_sasb_responses = frappe.whitelist()(generate_sasb_responses)
    get_sasb_summary = frappe.whitelist()(get_sasb_summary)


def _assessment_guard(name, write=False):
    if frappe is None:
        raise RuntimeError("Velora framework runtime is required")
    if not frappe.has_permission("Code Compliance Assessment", "write" if write else "read", name):
        frappe.throw("You do not have permission to open this code assessment", frappe.PermissionError)


def get_code_assessment(name):
    """A code assessment as the screen shows it: each principle with its answer and the recommended practices beneath it."""
    _assessment_guard(name)
    a = frappe.get_doc("Code Compliance Assessment", name)
    prac = {}
    for p in a.get("practice_responses") or []:
        prac.setdefault(p.principle_number, []).append({"reference": p.reference, "requirement": p.requirement, "status": p.status, "how": p.how_applied_or_explanation or "", "evidence": p.evidence_reference or ""})
    principles = [{"number": r.principle_number, "part": r.part, "title": r.title, "status": r.status, "how": r.how_applied_or_explanation or "", "evidence": r.evidence_reference or "", "owner": r.responsible_owner or "",
                   "practices": prac.get(r.principle_number, [])} for r in sorted(a.get("responses") or [], key=lambda r: r.principle_number)]
    return {"name": a.name, "governance_entity": a.governance_entity, "governance_code": a.governance_code, "assessment_period": a.assessment_period, "principles": principles,
            "summary": {"applied": a.applied_count, "partial": a.partial_count, "explained": a.explained_count, "not_assessed": a.not_assessed_count, "application_percent": a.application_percent,
                        "practices_applied": a.practice_applied_count, "practices_assessed": a.practice_assessed_count, "practices_in_scope": a.practice_total_count, "practice_application_percent": a.practice_application_percent}}


def save_code_assessment_answers(name, principles=None, practices=None):
    """Update answers by principle number and practice reference. Nothing is saved unless every departure is explained."""
    _assessment_guard(name, write=True)
    a = frappe.get_doc("Code Compliance Assessment", name)
    p_by = {r.principle_number: r for r in a.get("responses") or []}
    r_by = {r.reference: r for r in a.get("practice_responses") or []}
    for x in principles or []:
        row = p_by.get(int(x["number"]))
        if row is None:
            frappe.throw(f"No principle {x['number']} in this assessment.")
        row.status = x.get("status") or row.status; row.how_applied_or_explanation = x.get("how", row.how_applied_or_explanation); row.evidence_reference = x.get("evidence", row.evidence_reference)
    for x in practices or []:
        row = r_by.get(str(x["reference"]))
        if row is None:
            frappe.throw(f"No practice {x['reference']} in this assessment.")
        row.status = x.get("status") or row.status; row.how_applied_or_explanation = x.get("how", row.how_applied_or_explanation); row.evidence_reference = x.get("evidence", row.evidence_reference)
    a.save()
    return get_code_assessment(name)


if frappe is not None:
    get_code_assessment = frappe.whitelist()(get_code_assessment)
    save_code_assessment_answers = frappe.whitelist()(save_code_assessment_answers)
