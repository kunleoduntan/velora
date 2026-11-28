"""The ProjectOne guide is one self-contained page whose links and numbering hold, and which names only things that exist."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "velora_projectone" / "docs" / "PROJECTONE-GUIDE-v2.25.2.html").read_text()
DOCTYPES = {json.loads(p.read_text())["name"] for p in (ROOT / "velora_projectone" / "projectone" / "doctype").glob("*/*.json")}


def test_guide_is_self_contained():
    assert not re.findall(r'(?:src|href)="(?:https?:)?//', PAGE) and "<link " not in PAGE and PAGE.count("<script") == 1
    assert "Powered by <b>Velora BiZ Solutions</b>" in PAGE and 'name="viewport"' in PAGE


def test_links_resolve_and_sections_are_numbered():
    page = re.sub(r"<script>.*?</script>", "", PAGE, flags=re.S)
    ids = set(re.findall(r'id="([^"]+)"', page))
    assert not [a for a in re.findall(r'href="#([^"]+)"', page) if a not in ids]
    sections = re.findall(r'<section id="([^"]+)"', PAGE)
    assert len(sections) == len(set(sections)) == 16
    assert all(f'<span class="n">{i}</span>' in PAGE for i in range(1, 17))


def test_every_document_named_in_bold_exists():
    named = {b for b in re.findall(r"<b>([^<]+)</b>", PAGE) if b.startswith(("Project ", "Resource ", "Task "))}
    ignore = {"Project Manager", "Project User", "Project Finance Integration", "Project Manager Workbench", "Project Schedule Workspace",
              "Project Financial Control", "Project Delivery"}
    assert not [n for n in named - ignore if n not in DOCTYPES and n.rstrip("s") not in DOCTYPES], named - ignore - DOCTYPES
