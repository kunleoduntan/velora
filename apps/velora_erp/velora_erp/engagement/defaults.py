"""Standard message templates and occasions, created once and never overwritten (edit them freely)."""
from __future__ import annotations

from datetime import date

from velora import db, new_doc

T = [  # name, kind, audience, emblem, subject, heading, body, button label
 ("Customer Birthday", "Birthday", "Customer", "", "Happy birthday, {{ first_name }}!", "Happy Birthday",
  "Dear {{ first_name }},\n\nEveryone at {{ company }} wishes you a very happy birthday. Thank you for trusting us; it is a real pleasure to serve you.\n\nMay the year ahead bring you good health, joy and success. Enjoy your special day!", ""),
 ("Supplier Birthday", "Birthday", "Supplier", "", "Happy birthday, {{ first_name }}!", "Happy Birthday",
  "Dear {{ first_name }},\n\nOn behalf of {{ company }}, warm birthday wishes to you. We are grateful for the reliable service and the good working relationship we share.\n\nWishing you a wonderful day and a prosperous year ahead.", ""),
 ("Employee Birthday", "Birthday", "Employee", "", "Happy birthday, {{ first_name }}!", "Happy Birthday",
  "Dear {{ first_name }},\n\nEveryone at {{ company }} wishes you a happy birthday. Thank you for everything you bring to the team.\n\nHave a wonderful day!", ""),
 ("Employee Work Anniversary", "Work Anniversary", "Employee", "", "Congratulations on {{ years_text }} with {{ company }}", "Happy Work Anniversary",
  "Dear {{ first_name }},\n\nToday marks {{ years_text }} since you joined {{ company }}. Thank you for your dedication, your effort and the way you contribute to the team.\n\nHere is to many more years together.", ""),
 ("Customer Anniversary", "Partnership Anniversary", "Customer", "", "{{ years_text }} together, {{ first_name }}", "Thank You for {{ years_text }}",
  "Dear {{ first_name }},\n\nIt is {{ years_text }} since you first chose {{ company }}, and we are truly grateful. Your trust is what keeps us improving.\n\nThank you, and here is to the years ahead.", ""),
 ("Supplier Anniversary", "Partnership Anniversary", "Supplier", "", "{{ years_text }} of working together", "{{ years_text }} Together",
  "Dear {{ first_name }},\n\nThis month marks {{ years_text }} of working together. Thank you for being a dependable partner to {{ company }}.\n\nWe look forward to many more years.", ""),
 ("Holiday Greeting", "Holiday", "All", "", "{{ occasion }} greetings from {{ company }}", "{{ occasion }}",
  "Dear {{ first_name }},\n\nOn {{ occasion }}, everyone at {{ company }} sends you warm wishes. Thank you for being part of our year.\n\nWe hope you and your loved ones enjoy a time of peace, rest and joy.", ""),
 ("Customer Win Back", "Win Back", "Customer", "", "It has been a while, {{ first_name }}. We miss you!", "We Miss You",
  "Dear {{ first_name }},\n\nIt has been {{ days_text }} since we last served you, and we have missed you. A lot has happened at {{ company }}, and we would love to catch up and help you again.\n\nIf there is anything we could have done better, we would value hearing it. Simply reply to this message.", "Get in touch"),
 ("Supplier Win Back", "Win Back", "Supplier", "", "We value working with you, {{ first_name }}", "Let's Reconnect",
  "Dear {{ first_name }},\n\nIt has been {{ days_text }} since we last worked together. {{ company }} values the relationship, and we would be glad to hear about your latest products and terms.\n\nPlease keep us in mind.", "Get in touch"),
]
OCCASIONS = [("New Year's Day", 1, 1), ("Workers' Day", 5, 1), ("Christmas Day", 12, 25)]


def ensure():
    from .service import settings
    settings()
    for name, kind, aud, emblem, subject, heading, body, button in T:
        if not db.exists("Moment Template", name):
            new_doc("Moment Template", template_name=name, moment_kind=kind, audience=aud, enabled=1, emblem=emblem, subject=subject, heading=heading, body=body,
                    button_label=button).insert(ignore_permissions=True)
    for name, m, d in OCCASIONS:
        if not db.exists("Occasion", name):
            new_doc("Occasion", occasion_name=name, occasion_date=date(2000, m, d), repeat_yearly=1, enabled=1, to_customers=1, to_suppliers=1, to_employees=1).insert(ignore_permissions=True)
