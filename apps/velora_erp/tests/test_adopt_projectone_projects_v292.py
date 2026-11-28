"""Projects created in the old Finance module keep working after the upgrade."""
import velora
from sqlalchemy import text

from velora import db, get_doc
from velora.db.tables import table_name
from velora_erp.setup import after_install
from velora_erp.patches.v2_92 import adopt_projectone_projects


def test_old_finance_projects_are_adopted(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path/'p.db'}", apps=["velora_erp", "velora_projectone"], developer_mode=True)
    velora.init(); velora.migrate(); after_install()
    t = table_name("Project")
    with db.transaction() as conn:
        for col in ("project_name", "budget_amount"):
            conn.execute(text(f'ALTER TABLE "{t}" ADD COLUMN {col} TEXT'))
        conn.execute(text(f'INSERT INTO "{t}" (name, project_code, project_name, budget_amount, status, owner) VALUES (\'OLD-1\', \'OLD-1\', \'Old Road\', 5000, \'Active\', \'ada@x.com\')'))
    adopt_projectone_projects.execute()
    adopt_projectone_projects.execute()  # safe to repeat
    doc = get_doc("Project", "OLD-1")
    assert doc.title == "Old Road" and doc.status == "In Progress"
    assert float(doc.approved_budget) == 5000 and doc.project_manager == "ada@x.com"
