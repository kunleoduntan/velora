"""The condition language and the templates take text typed by an administrator: they must never run arbitrary code."""
import pytest

from velora_notify import expr as X, templating as T
from velora_notify.expr import DocView, ExprError


def ev(src, **ctx):
    base = {**X.base_functions(), "doc": DocView({"status": "Approved", "total": 1500, "name": "SO-1", "items": [{"qty": 2, "amount": 10}, {"qty": 3, "amount": 5}], "due_date": "2026-03-10", "customer": "Acme"}),
            "old": DocView({"status": "Draft"})}
    base.update(ctx)
    return X.evaluate(src, base)


@pytest.mark.parametrize("src,expected", [
    ('doc.status == "Approved"', True), ('doc.status != "Approved"', False), ("doc.total > 1000 and doc.total <= 1500", True), ("not doc.total < 100", True),
    ('doc.customer in ["Acme", "Bola"]', True), ('doc.customer not in ("X",)', True), ('old.status == "Draft" and doc.status == "Approved"', True),
    ("doc.total * 2 - 500", 2500), ("doc.total / 3 > 400", True), ("doc.total % 7", 2), ('lower("ABC")', "abc"), ('upper(doc.status)', "APPROVED"),
    ("count(doc.items)", 2), ('sum_of(doc.items, "amount")', 15), ("len(doc.items) == 2", True), ('"yes" if doc.total > 1 else "no"', "yes"),
    ("doc.missing_field is None", True), ("doc.missing_field == 5", False), ("doc.missing_field > 5", False), ("-doc.total < 0", True),
    ('startswith(doc.name, "SO")', True), ('contains(doc.customer, "cm")', True), ("max(1, 5, 3) == 5 and min(4, 2) == 2 and abs(-3) == 3 and round(2.6) == 3", True),
    ('days_until(doc.due_date)', 9), ('days_since(doc.due_date)', -9), ("days_until(doc.nope) is None", True), ("doc.items[0].qty", 2), ("doc.items[5]", None), ("1 < doc.total < 2000", True),
])
def test_the_language_works(src, expected):
    from datetime import date
    assert ev(src, **{**X.base_functions(today=date(2026, 3, 1))}) == expected


@pytest.mark.parametrize("src,frag", [
    ("__import__('os').system('id')", "Only plain functions can be called"), ("doc.__class__", "'__class__' is not allowed"), ("doc._d", "'_d' is not allowed"),
    ("().__class__.__bases__", "is not allowed"), ("[x for x in doc.items]", "ListComp is not allowed"), ("lambda: 1", "Lambda is not allowed"),
    ("f'{doc.name}'", "JoinedStr is not allowed"), ("open('/etc/passwd')", "'open' is not a function"), ("eval('1')", "'eval' is not a function"),
    ("doc.status.upper()", "Only plain functions can be called"), ("doc.status.upper", "Cannot read '.upper' here"), ("(1).real", "Cannot read '.real' here"), ("{'a': 1}", "Dict is not allowed"), ("doc.total := 5", "Not a valid expression"),
    ("x = 1", "Not a valid expression"), ("1 if", "Not a valid expression"), ("", "empty"), ("   ", "empty"), ("a" * 600, "longer than 500"),
    ("lower(1, 2, 3, 4, 5)", "at most 4"), ("lower(s=1)", "at most 4"), ("doc.items.append(1)", "Only plain functions"), ("b'bytes'", "Only text, numbers"),
    ("+".join(["1"] * 130), "too complicated"), ("1/0", "Division by zero"), ("'a' + 1", "Cannot add text and a number"), ("yield 1", "Not a valid expression"),
    ("await x", "Await is not allowed"), ("print", "Unknown name 'print'"), ("doc", "x"),
])
def test_the_language_refuses_everything_dangerous_with_a_clear_reason(src, frag):
    if src == "doc":
        assert isinstance(ev(src), DocView)                                                                  # a bare record is fine to read; just not to dig into
        return
    with pytest.raises(ExprError) as e:
        ev(src)
    assert frag in str(e.value)


def test_deeply_nested_input_is_refused_not_a_crash():
    with pytest.raises(ExprError, match="nested too deeply|too complicated"):
        ev("-" * 40 + "1")                                                                                       # 40 nested negations


def test_functions_can_be_restricted_to_a_whitelist():
    X.compile_expr("lower(doc.status)", functions={"lower"})
    with pytest.raises(ExprError, match="'upper' is not a function you can use here"):
        X.compile_expr("upper(doc.status)", functions={"lower"})


def test_a_record_view_is_read_only_and_hides_internals():
    d = DocView({"a": 1, "rows": [{"x": 1}]})
    assert d.a == 1 and d.b is None and d.rows[0].x == 1
    with pytest.raises(AttributeError):
        d.a = 2
    assert repr(d) == "<record >" and DocView(None).anything is None

@pytest.mark.parametrize("src", ["{{ ''.__class__.__mro__ }}", "{{ doc.__class__ }}", "{% for c in ''.__class__.__mro__[1].__subclasses__() %}{{ c }}{% endfor %}",
                                 "{{ lipsum.__globals__ }}", "{{ cycler.__init__.__globals__ }}", "{{ config }}", "{{ self._TemplateReference__context }}"])
def test_templates_cannot_reach_python_internals(src):
    try:
        out = T.render(src, {"doc": DocView({"name": "X"})})
    except T.TemplateError:
        return                                                                                                # refused outright
    assert "class" not in out and "mro" not in out and "globals" not in out and out.strip() in ("", "None")  # or rendered as nothing; never leaks anything


def test_templates_render_values_with_the_money_and_date_filters():
    from datetime import date
    ctx = {"doc": DocView({"name": "SINV-1", "grand_total": "1234567.5", "due_date": date(2026, 3, 9), "customer": "Bola <b>Stores</b>"}), "event": "Submit"}
    assert T.render("{{ doc.name }}: {{ doc.grand_total|money }} due {{ doc.due_date|date }} ({{ event }})", ctx) == "SINV-1: 1,234,567.50 due 09 Mar 2026 (Submit)"
    assert T.render("{{ doc.missing }}|{{ doc.grand_total|money(0) }}|{{ 'x'|money }}|{{ None|date }}", ctx) == "|1,234,568|x|"
    assert T.render("{% if doc.customer %}Hello {{ doc.customer }}{% endif %}", ctx, html=True) == "Hello Bola &lt;b&gt;Stores&lt;/b&gt;"       # HTML mode escapes
    assert "<b>" in T.render("{{ doc.customer }}", ctx)                                                                                          # text mode does not


def test_template_limits_and_errors_are_clear():
    with pytest.raises(T.TemplateError, match="at most 5000"):
        T.validate("x" * 5001)
    with pytest.raises(T.TemplateError, match="line 1"):
        T.validate("{{ doc.name ")
    with pytest.raises(T.TemplateError, match="line 2"):
        T.validate("ok\n{% if %}")
    assert len(T.render("{% for i in range(5000) %}0123456789{% endfor %}", {})) == 20000                                                 # output is capped
    assert T.render("{% for i in range(3) %}{{ i }},{% endfor %}", {}) == "0,1,2,"
    with pytest.raises(T.TemplateError):
        T.render("{{ range(10**9)|list|length }}", {})                                                                                       # the sandbox caps range()
