from velora import Document, get_doc, throw
from velora_erp.treasury import service as svc

OPS = {"<=": lambda v, t: v <= t, "<": lambda v, t: v < t, ">=": lambda v, t: v >= t, ">": lambda v, t: v > t}


def evaluate(value, op, limit, margin=0):
    v, t, m = float(value), float(limit), float(margin or 0)
    ok = OPS[op](v, t)
    headroom = (t - v) if op in ("<=", "<") else (v - t)
    return ("Breach" if not ok else ("Warning" if m > 0 and headroom <= m else "Compliant")), headroom


class CovenantTest(Document):
    def validate(self):
        fac = get_doc("Financing Facility", self.facility, ignore_permissions=True)
        if fac.docstatus != 1:
            throw("Choose a submitted facility.")
        cov = next((c for c in fac.covenants or [] if c.covenant_name.strip().lower() == (self.covenant_name or "").strip().lower()), None)
        if not cov:
            throw(f"{fac.facility_name} has no covenant named {self.covenant_name}.")
        self.covenant_name, self.operator, self.threshold, self.warning_margin = cov.covenant_name, cov.operator, cov.threshold, cov.warning_margin or 0
        self.status, self.headroom = evaluate(self.actual_value, cov.operator, cov.threshold, cov.warning_margin)
        self.title = f"{self.covenant_name} {self.tested_on}"

    def after_insert(self):
        if self.status == "Breach":
            try:
                from velora_notify.engine import trigger
                trigger("treasury_covenant_breach", self, key=self.name)
            except Exception:  # noqa: BLE001  (notification rules are optional)
                pass
