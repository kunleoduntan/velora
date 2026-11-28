from datetime import date
from decimal import Decimal
from types import SimpleNamespace as N

import pytest

from velora import printing_jinja as pj
from velora.exceptions import ValidationError

META = N(table_fields=[N(fieldname="lines")])
VALUES = {"name": "SI-00000002", "party": "CUST-1", "invoice_date": date(2026, 11, 27), "due_date": date(2026, 12, 27), "currency": "NGN",
          "net_amount": Decimal("1000"), "grand_total": Decimal("1075"),
          "lines": [{"item_code": "A1", "description": "Widget", "quantity": 2, "rate": Decimal("500"), "amount": Decimal("1000"), "batch": "B-7",
                     "tax_account": "VAT", "tax_rate": 7.5, "tax_amount": Decimal("75")}]}

FRAPPE_FORMAT = """{%- set tc_html = doc.terms -%}{%- if not tc_html and doc.tc_name -%}{%- set tc_html = frappe.db.get_value("Terms and Conditions", doc.tc_name, "terms") -%}{%- endif -%}
<h1>SALES INVOICE</h1> Invoice No: {{ doc.name }} | Date: {{ frappe.utils.formatdate(doc.posting_date, "dd-MM-yyyy") }}
{{ frappe.db.get_value("Company", doc.company, "company_name") or doc.company }}
Printed: {{ frappe.utils.now_datetime().strftime("%d-%m-%Y") }} Customer: {{ doc.customer_name }}
{% for item in doc.items %}<tr><td>{{ loop.index }}</td><td>{{ item.item_code }}</td><td>{{ item.item_name or item.description }}{% if item.batch_no %} | Batch: {{ item.batch_no }}{% endif %}</td><td>{{ item.qty }}</td>
<td>{{ frappe.format_value(item.rate, {'fieldtype': 'Currency', 'options': doc.currency}) }}</td></tr>{% endfor %}
{% for tax in doc.taxes %}{{ tax.account_head }} ({{ tax.rate }}%): {{ frappe.format_value(tax.tax_amount, {'fieldtype': 'Currency', 'options': doc.currency}) }}{% endfor %}
Net {{ frappe.format_value(doc.net_total, {'fieldtype': 'Currency'}) }}"""


def test_frappe_style_format_renders_instead_of_showing_raw_tags():
    out = pj.render_template(FRAPPE_FORMAT, VALUES, META, party_title="Acme Ltd")
    assert "{%" not in out and "{{" not in out
    assert "Invoice No: SI-00000002" in out and "Date: 27-11-2026" in out
    assert "Customer: Acme Ltd" in out
    assert "<td>1</td><td>A1</td><td>Widget | Batch: B-7</td><td>2</td>" in out
    assert "<td>500.00</td>" in out and "VAT (7.5%): 75.00" in out and "Net 1,000.00" in out


def test_simple_field_placeholders_still_work_and_values_are_escaped():
    values = dict(VALUES, name="<b>X</b>")
    assert pj.render_template("{{name}} / {{ name }}", values, META) == "&lt;b&gt;X&lt;/b&gt; / &lt;b&gt;X&lt;/b&gt;"


def test_template_cannot_reach_python_internals():
    # The sandbox answers an unsafe lookup with an empty value (or an error); either way nothing of the interpreter is printed.
    for template in ("{{ doc.__class__ }}", "{{ ''.__class__.__mro__[1].__subclasses__() }}", "{{ frappe.__init__.__globals__ }}"):
        try: out = pj.render_template(template, VALUES, META)
        except ValidationError: continue
        assert "class" not in out and "object" not in out and "{" not in out


def test_syntax_errors_are_reported_with_line_before_saving():
    with pytest.raises(ValidationError, match="line 2"):
        pj.validate("ok\n{% for x in %}")


def test_pdf_keeps_tables_and_is_a_valid_pdf():
    from velora import printing
    blocks = printing._pdf_blocks("<h1>Invoice</h1><p>Hello</p><table><tr><th>#</th><th>Item</th></tr><tr><td>1</td><td>Widget</td></tr></table>")
    assert blocks[0] == ("h1", "Invoice") and blocks[2] == ("table", [["#", "Item"], ["1", "Widget"]])
    assert printing.to_pdf("<h1>Invoice</h1><table><tr><td>1</td><td>x</td></tr></table>").startswith(b"%PDF")
