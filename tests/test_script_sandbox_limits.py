"""A server script saved by an administrator must not be able to freeze a worker, exhaust memory, or step outside its own document."""
import subprocess
import sys
from pathlib import Path

import pytest

from velora import new_doc, scripts
from velora.exceptions import ValidationError

ROOT = Path(__file__).resolve().parent.parent
PATHS = [str(ROOT), str(ROOT / "apps" / "velora_demo")]
BIG = "*".join(["10"] * 12)                         # 10**12


def attack(code):
    r = subprocess.run([sys.executable, str(ROOT / "tests" / "script_attack.py"), code, *PATHS], capture_output=True, text=True, timeout=25)
    line = next((ln for ln in r.stdout.splitlines() if ln.startswith("VERDICT")), "")
    assert line, f"the attacker script produced no verdict (crashed?): {r.stderr[-300:]}"
    return line


@pytest.mark.parametrize("label,code,frag", [
    ("a range too long to ever finish", f"x = sum(range({BIG}))", "range() may produce at most"),
    ("a huge string", f"x = 'x' * ({BIG} * 10)", "too large"),
    ("a huge list", f"x = [0] * ({BIG})", "too large"),
    ("repetition by augmented assignment", f"x = 'ab'\nx *= {BIG}", "too large"),
    ("a huge text-format width", "x = '%999999999d' % 1", "text-format width"),
    ("a star width", "x = '%*d' % (5, 1)", "text-format width"),
    ("doubling a string 40 times", 'x = "ab"\n' + "x = x + x\n" * 40, "too large"),
    ("doubling by augmented assignment", 'x = "ab"\n' + "x += x\n" * 40, "too large"),
    ("squaring a number 40 times", "n = 99999\n" + "n = n * n\n" * 40, "number that is too large"),
    ("doubling a list", "x = [1, 2, 3]\n" + "x = x + x\n" * 40, "too large"),
])
def test_resource_bombs_are_refused_instantly_in_a_contained_process(label, code, frag):
    verdict = attack(code)
    assert verdict.startswith("VERDICT REFUSED") and frag in verdict, verdict                  # never RAN, MEMORY or RAW; and a timeout here fails the test rather than hanging the suite
    assert "seconds=0." in verdict or "seconds=1." in verdict


@pytest.mark.parametrize("field", ["docstatus", "owner", "name", "creation", "modified", "modified_by"])
def test_a_script_cannot_write_the_documents_system_columns(field):
    verdict = attack(f"doc.{field} = 1")
    assert "REFUSED" in verdict and "is not writable" in verdict and "docstatus=0 owner=None name=None" in verdict


# ---- in-process: behaviour that must keep working ----
def run(code, **fields):
    doc = new_doc("Customer", customer_name="Acme", **fields)
    scripts._run_server_script({"code": code, "name": "t", "id": None, "version": 1}, doc)
    return doc


def test_ordinary_scripts_still_work(site):
    d = run('doc.customer_name = "%s-%d" % ("A", sum(range(100)))\nx = [1, 2] * 3\ny = 2 + 3 * 4 % 5\nif len(x) == 6 and y == 4:\n    doc.email = "ok@x.ng"')
    assert d.customer_name == "A-4950" and d.email == "ok@x.ng"
    d = run("doc.credit_limit = doc.credit_limit or 0\ndoc.credit_limit += 5\ndoc.credit_limit *= 3")
    assert d.credit_limit == 15                                                                # augmented assignment on a document field still works


def test_the_limits_are_exactly_at_the_documented_boundaries(site):
    run(f"x = sum(range({scripts.MAX_RANGE}))")
    with pytest.raises(ValidationError, match="range"):
        run(f"x = sum(range({scripts.MAX_RANGE + 1}))")
    run(f"x = 'a' * {scripts.MAX_SEQUENCE}")
    with pytest.raises(ValidationError, match="too large"):
        run(f"x = 'a' * {scripts.MAX_SEQUENCE + 1}")
    run("x = 'a' * 50000 + 'b' * 50000")                                                       # concatenation up to the limit
    with pytest.raises(ValidationError, match="too large"):
        run("x = 'a' * 50000 + 'b' * 50001")
    run("x = 2 * 2 * 2 * 2 * 2 * 2 * 2 * 2")
    run("x = 1 % 7 + 4 % 3 * 2")
    for bad in ("x = range(0, 10**9, 1)", "x = range(-5000, 5001)"):                          # a computed range is checked too
        with pytest.raises(ValidationError):
            run(bad.replace("10**9", "1000000000"))


def test_scripts_can_read_system_columns_but_never_write_them(site):
    d = run("if doc.docstatus == 0:\n    doc.customer_name = 'draft'")
    assert d.customer_name == "draft" and d.docstatus == 0


def test_a_runtime_error_names_the_script_instead_of_failing_with_a_server_error(site):
    for code, frag in (("x = 1 / 0", "ZeroDivisionError"), ("x = doc.no_such_field", "AttributeError"), ("x = 'a' + 1", "TypeError"), ("x = int('abc')", "ValueError")):
        with pytest.raises(ValidationError, match=rf"Server Script 't' failed: {frag}"):
            run(code)
    with pytest.raises(ValidationError, match="plain throw"):
        run("throw('plain throw')")                                                            # a deliberate throw() is passed through untouched


def test_scripts_cannot_name_the_guard_helpers_or_reach_around_them():
    for code in ("x = _vl_add('a', 'b')", "x = _vl_mul", "y = __builtins__"):
        with pytest.raises(ValidationError, match="Private and dunder names"):
            scripts._compile_server_script(code, "t")
    for code in ("x = doc.__class__", "x = (1).bit_length()", "x = 'a'.join", "x = [].__class__", "x = str.format"):
        with pytest.raises(ValidationError, match="Unsafe Server Script"):
            scripts._compile_server_script(code, "t")


def test_a_script_is_compiled_once_per_saved_version(site, monkeypatch):
    scripts._COMPILED.clear()
    real, calls = scripts._compile_server_script, []
    monkeypatch.setattr(scripts, "_compile_server_script", lambda src, name="x": (calls.append(1), real(src, name))[1])
    row = {"code": "doc.email = 'a@b.ng'", "name": "t", "id": "s1", "version": 1}
    for _ in range(5):
        scripts._run_server_script(row, new_doc("Customer", customer_name="A"))
    assert len(calls) == 1
    scripts._run_server_script({**row, "version": 2, "code": "doc.email = 'c@d.ng'"}, new_doc("Customer", customer_name="A"))
    assert len(calls) == 2                                                                      # a new version is compiled, never served from the old cache


def test_the_script_table_is_not_re_reflected_on_every_document_event(site, monkeypatch):
    scripts.ensure()
    scripts._table_known.clear()
    seen = []
    real = scripts.inspect
    monkeypatch.setattr(scripts, "inspect", lambda c: (seen.append(1), real(c))[1])
    for _ in range(6):
        scripts.run_server_scripts(new_doc("Customer", customer_name="A"), "validate")
    assert len(seen) == 1
