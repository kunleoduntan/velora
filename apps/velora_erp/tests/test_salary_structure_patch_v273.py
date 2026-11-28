import velora
import velora_erp.hr  # noqa: F401  (script reports import it while the registry loads)
from sqlalchemy import insert, select
from velora import db
from velora.db.tables import get_table


def test_patch_moves_legacy_component_rows_into_the_two_tables(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path/'p.db'}", apps=["velora_erp", "velora_projectone"], developer_mode=True)
    velora.init(); velora.migrate()
    try:
        t = get_table("Salary Structure Component")
        base = dict(parent="SS-1", parenttype="Salary Structure", parentfield="components")
        with db.transaction() as c:
            for name, kind in (("r1", "Earning"), ("r2", "Deduction"), ("r3", "Employer Contribution"), ("r4", "Loan Repayment")):
                c.execute(insert(t).values(name=name, component_type=kind, **base))
        from velora_erp.patches.v2_73.split_salary_structure_tables import execute
        execute(); execute()                                         # idempotent
        with db.transaction() as c:
            got = {r["name"]: r["parentfield"] for r in c.execute(select(t.c.name, t.c.parentfield)).mappings()}
        assert got == {"r1": "earnings", "r2": "deductions", "r3": "deductions", "r4": "deductions"}
    finally:
        velora.shutdown()
