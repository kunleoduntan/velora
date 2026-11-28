"""The ERP tutorial and manual stays one self-contained page and mentions only things that exist."""
import re
from pathlib import Path

PAGE = next((Path(__file__).resolve().parents[1] / "velora_erp" / "docs").glob("VELORAERP-USER-MANUAL-v*.html")).read_text()


def test_manual_is_self_contained():
    assert not re.findall(r'(?:src|href)="(?:https?:)?//', PAGE) and "<link " not in PAGE and PAGE.count("<script") == 1
    assert "Powered by <b>Velora BiZ Solutions</b>" in PAGE and 'name="viewport"' in PAGE


def test_every_internal_link_resolves_and_sections_are_numbered():
    page = re.sub(r"<script>.*?</script>", "", PAGE, flags=re.S)       # (the script builds its own links at run time)
    ids = set(re.findall(r'id="([^"]+)"', page))
    assert not [a for a in re.findall(r'href="#([^"]+)"', page) if a not in ids]
    sections = re.findall(r'<section id="([^"]+)"', PAGE)
    assert len(sections) == len(set(sections)) >= 25
    assert all(f'<span class="n">{i}</span>' in PAGE for i in range(1, len(sections) + 1))


def test_screens_named_in_the_manual_are_real_doctypes_or_routes():
    hooks = (Path(__file__).resolve().parents[1] / "velora_erp" / "hooks.py").read_text()
    for fn in ("velora_erp.support.jobs.check_sla", "velora_erp.investments.jobs.accrue_month_end", "velora_erp.investments.jobs.watch_maturities", "velora_erp.support.jobs.auto_close"):
        assert fn in hooks
    for route in re.findall(r"<code>#/([a-z-]+)", PAGE):
        assert route in {"shortcuts", "financial-centre", "bank-reconciliation", "budgets", "controls-check", "gl-review", "finance", "operational-centre",
                         "tax-centre", "treasury-centre", "investments", "support", "broadcasts", "hr", "recruitment", "portal-access", "corrections", "updates", "settings", "rules", "migration"}, route


def test_ten_guided_tutorials_are_present_and_numbered():
    titles = re.findall(r"<h3>Tutorial (\d+): ", PAGE)
    assert titles == [str(i) for i in range(1, 11)]
    for words in ("Get Items From", "Customer Credit Exposure", "Customize Form", "Database speed", "Draw an approval workflow"):
        assert words in PAGE
    assert "finance.approval_authority" not in PAGE            # approval is a workflow, not a coded setting
