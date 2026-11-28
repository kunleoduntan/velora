from velora import Document, throw


class QualityInspectionTemplate(Document):
    def validate(self):
        names = set()
        for index, row in enumerate(self.parameters or [], 1):
            key = (row.parameter or "").strip().lower()
            if key in names:
                throw(f"Parameter {row.parameter} is listed twice.")
            names.add(key)
            if row.kind == "Numeric" and row.min_value not in (None, "") and row.max_value not in (None, "") and float(row.min_value) > float(row.max_value):
                throw(f"Row {index} ({row.parameter}): the minimum is above the maximum.")
            if row.kind == "Numeric" and row.min_value in (None, "") and row.max_value in (None, ""):
                throw(f"Row {index} ({row.parameter}): give a minimum, a maximum or both, or measure it as Pass/Fail.")
