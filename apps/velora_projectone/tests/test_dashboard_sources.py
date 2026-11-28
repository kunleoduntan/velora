from velora_projectone.projectone.reports.dashboard_sources import collect_core_dashboard_data
from velora_projectone.projectone.reports.dashboards import (
    build_dashboard_suite, programme_dashboard, benefits_dashboard, schedule_dashboard,
)


class Actor:
    actor_id = 'user@example.test'
    company_id = 'COMP-001'


class FakeRepository:
    def __init__(self):
        self.rows = {
            'Project': [{'name':'P-001','title':'ERP Rollout','status':'In Progress','company':'COMP-001'}],
            'Project Task': [
                {'name':'T-001','project':'P-001','title':'Design','duration_days':3,'status':'In Progress'},
                {'name':'T-002','project':'P-001','title':'Build','duration_days':4,'status':'Open'},
            ],
            'Task Dependency': [{'name':'D-001','project':'P-001','predecessor':'T-001','successor':'T-002','relationship':'FS','lag_days':0}],
            'Project Benefit': [{'name':'B-001','project':'P-001','benefit_name':'Faster close','target_value':100,'actual_value':60,'realisation_status':'At Risk'}],
        }
    def get(self, actor, doctype, name):
        return next((r for r in self.rows.get(doctype,[]) if r['name']==name),None)
    def list(self, actor, doctype, *, filters=None, limit=100, offset=0):
        rows=list(self.rows.get(doctype,[]))
        for key,value in (filters or {}).items():
            rows=[r for r in rows if r.get(key)==value]
        return rows[offset:offset+limit]


def test_native_dashboard_source_uses_repository_scope_and_builds_task_dependencies():
    result=collect_core_dashboard_data(FakeRepository(),Actor(),project_id='P-001')
    assert len(result['data']['projects']) == 1
    assert result['data']['tasks'][1]['dependencies'][0]['predecessor'] == 'T-001'
    assert result['metadata']['permission_filtered'] is True


def test_programme_and_benefit_dashboard_metrics():
    programme=programme_dashboard({'programmes':[{'status':'Active'}], 'projects':[{'programme':'PRG-1'},{}]})
    assert programme['kpis']['active_programmes']==1
    assert programme['kpis']['unassigned_projects']==1
    benefits=benefits_dashboard({'benefits':[{'target_value':100,'actual_value':60,'realisation_status':'At Risk'}]})
    assert benefits['kpis']['benefits_under_target']==1
    assert benefits['kpis']['benefits_at_risk']==1


def test_schedule_dashboard_calculates_critical_path_from_authorised_dependencies():
    result=schedule_dashboard({'tasks':[
        {'name':'T1','title':'Design','duration_days':3,'dependencies':[]},
        {'name':'T2','title':'Build','duration_days':4,'dependencies':[{'predecessor':'T1','type':'FS','lag':0}]},
    ]})
    assert result['kpis']['critical_activities']==2
    assert len(result['critical_path'])==2


def test_dashboard_suite_has_complete_enterprise_dashboard_set():
    result=build_dashboard_suite({})
    assert set(result['dashboards']) == {'portfolio','delivery','schedule','resources','financial','commercial','risk','agile','quality','programme','benefits'}
