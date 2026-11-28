from velora_governance.governance.services.governance_report_catalog import report_catalog, get_report_definition, apply_filters, summarize, build_report


def test_catalog_contains_board_compliance_risk_exception_and_esg_reports():
    ids={r["report_id"] for r in report_catalog()}
    assert {"board_register","board_actions","obligations","risk_register","control_assurance","exceptions","esg_readiness","ghg_emissions","materiality","sustainability_reports"}.issubset(ids)
    assert len(ids) >= 20


def test_unknown_report_rejected():
    try:
        get_report_definition("not-a-report")
    except ValueError as exc:
        assert "Unknown Governance report" in str(exc)
    else:
        raise AssertionError("Expected unknown report validation")


def test_filters_and_summary_are_deterministic():
    rows=[{"status":"Open","severity":"High","score":7},{"status":"Closed","severity":"Low","score":2},{"status":"Open","severity":"Low","score":3}]
    filtered=apply_filters(rows,{"status":"Open"})
    summary=summarize(filtered,"severity")
    assert len(filtered)==2
    assert summary["record_count"]==2
    assert summary["totals"]["score"]==10
    assert summary["groups"]==[{"label":"High","count":1},{"label":"Low","count":1}]


def test_report_returns_metadata_summary_rows_and_filters():
    result=build_report("board_actions",[{"name":"BA-1","action_status":"Open","progress_percent":20},{"name":"BA-2","action_status":"Closed","progress_percent":100}],{"action_status":"Open"})
    assert result["title"]=="Board Action Register"
    assert result["summary"]["record_count"]==1
    assert result["rows"][0]["name"]=="BA-1"
    assert "progress_percent" in result["columns"]


def test_board_action_aging_report_calculates_deadline_buckets():
    result=build_report("board_action_aging",[
        {"name":"BA-1","action_title":"Overdue","due_date":"2026-11-20","action_status":"Open","priority":"High"},
        {"name":"BA-2","action_title":"Upcoming","due_date":"2026-12-05","action_status":"Open","priority":"Medium"},
        {"name":"BA-3","action_title":"Completed","due_date":"2026-11-01","action_status":"Completed","priority":"Low"},
    ],today="2026-11-27")
    assert result["summary"]["overdue_records"]==1
    assert result["summary"]["deadline_buckets"]
    assert result["rows"][0]["deadline_bucket"]=="Overdue"
    assert result["rows"][2]["deadline_bucket"]=="Completed/Terminal"


def test_ghg_report_calculates_emissions_totals():
    result=build_report("ghg_emissions",[
        {"name":"GHG-1","emissions_tco2e":1.25,"emissions_kgco2e":1250},
        {"name":"GHG-2","emissions_tco2e":2.75,"emissions_kgco2e":2750},
    ])
    assert result["summary"]["total_emissions_tco2e"]==4.0
    assert result["summary"]["total_emissions_kgco2e"]==4000


def test_esg_report_calculates_average_readiness():
    result=build_report("esg_readiness",[{"readiness_percent":50},{"readiness_percent":80},{"readiness_percent":90}])
    assert result["summary"]["average_readiness_percent"]==73.33


def test_catalog_fields_are_queryable_non_table_fields():
    import glob, json
    from velora_governance.governance.services.governance_report_catalog import REPORTS
    files=glob.glob('governance/doctype/*/*.json')
    docs={}
    for path in files:
        doc=json.load(open(path))
        docs[doc.get('name')]={f.get('fieldname'):f.get('fieldtype') for f in doc.get('fields',[])}
    non_queryable={'Table','Table MultiSelect','Attach','Attach Image','HTML','Section Break','Column Break','Tab Break','Button'}
    for report in REPORTS.values():
        fieldtypes=docs[report['doctype']]
        for field in report['fields']:
            assert field=='name' or fieldtypes.get(field) not in non_queryable, (report['doctype'],field,fieldtypes.get(field))


def test_report_documentation_and_page_files_exist():
    import json, pathlib
    page=json.load(open('page/governance_report_centre/governance_report_centre.json'))
    assert page['page_name']=='governance-report-centre'
    assert (pathlib.Path(__file__).resolve().parents[1]/'velora_governance'/'docs'/'REPORT-CATALOG-v11.6.0.html').exists()
    assert (pathlib.Path(__file__).resolve().parents[1]/'velora_governance'/'docs'/'governance-report-flow-v11.6.0.svg').exists()
    manual=(pathlib.Path(__file__).resolve().parents[1]/'velora_governance'/'page'/'governance_user_manual/governance_user_manual.js').read_text()
    assert 'id=\\"reports\\"' in manual
    assert 'Governance Report Centre' in manual


def test_report_catalog_exposes_safe_date_fields():
    catalog={r['report_id']:r for r in report_catalog()}
    assert catalog['board_actions']['date_fields']==['due_date','completion_date']
    assert catalog['meeting_calendar']['date_fields']==['scheduled_start','scheduled_end']
    assert catalog['risk_register']['date_fields']==[]


def test_risk_report_builds_5_by_5_matrix_from_numeric_likelihood_and_impact():
    result=build_report('risk_register',[
        {'name':'R-1','residual_likelihood':4,'residual_impact':5},
        {'name':'R-2','inherent_likelihood':2,'inherent_impact':3},
        {'name':'R-3','residual_likelihood':4,'residual_impact':5},
        {'name':'R-4','residual_likelihood':'Unknown','residual_impact':2},
    ])
    matrix=result['summary']['risk_matrix']['cells']
    assert len(matrix)==5 and all(len(row)==5 for row in matrix)
    assert matrix[3][4]==2
    assert matrix[1][2]==1
    assert sum(sum(row) for row in matrix)==3


def test_date_field_catalog_only_contains_fields_in_report_columns():
    from velora_governance.governance.services.governance_report_catalog import REPORTS, REPORT_DATE_FIELDS
    for report_id, date_fields in REPORT_DATE_FIELDS.items():
        assert report_id in REPORTS
        assert set(date_fields).issubset(set(REPORTS[report_id]['fields']))


def test_safe_date_filter_builder_supports_range_and_single_bound():
    from velora_governance.governance.services.governance_report_catalog import build_date_filters
    assert build_date_filters('board_actions','due_date','2026-01-01','2026-03-31') == {'due_date':['between',['2026-01-01','2026-03-31']]}
    assert build_date_filters('board_actions','due_date','2026-01-01',None) == {'due_date':['>=','2026-01-01']}
    assert build_date_filters('board_actions','due_date',None,'2026-03-31') == {'due_date':['<=','2026-03-31']}
    assert build_date_filters('risk_register','due_date','2026-01-01','2026-03-31') == {}


def test_safe_date_filter_builder_rejects_invalid_dates_and_reverse_ranges():
    from velora_governance.governance.services.governance_report_catalog import build_date_filters
    for args in [('board_actions','due_date','not-a-date',None),('board_actions','due_date','2026-03-31','2026-01-01')]:
        try:
            build_date_filters(*args)
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid date range must be rejected')


def test_period_comparison_calculates_absolute_percent_and_group_deltas():
    from velora_governance.governance.services.governance_report_catalog import compare_report_periods
    current={"record_count":12,"totals":{"progress_percent":650},"groups":[{"label":"Open","count":8},{"label":"Closed","count":4}]}
    prior={"record_count":10,"totals":{"progress_percent":500},"groups":[{"label":"Open","count":5},{"label":"Closed","count":5}]}
    result=compare_report_periods(current,prior)
    assert result["record_count"]=={"current":12,"prior":10,"delta":2,"percent_change":20.0,"comparison":"increase"}
    assert result["progress_percent"]["delta"]==150
    assert result["group_distribution"]["Open"]["percent_change"]==60.0
    assert result["group_distribution"]["Closed"]["comparison"]=="decrease"


def test_period_comparison_handles_zero_prior_without_divide_by_zero():
    from velora_governance.governance.services.governance_report_catalog import compare_report_periods
    result=compare_report_periods({"record_count":3,"groups":[{"label":"New","count":3}]},{"record_count":0,"groups":[]})
    assert result["record_count"]["percent_change"]==100.0
    assert result["group_distribution"]["New"]["percent_change"]==100.0
