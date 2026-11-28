from datetime import date
from velora import Document, throw, get_doc
def _d(v): return v if isinstance(v,date) else date.fromisoformat(str(v)[:10]) if v else None
class PerformanceGoal(Document):
    def validate(self):
        weight=float(self.weight or 0); progress=float(self.progress_percent or 0)
        if weight < 0 or weight > 100: throw("Goal weight must be between 0 and 100%.")
        if progress < 0 or progress > 100: throw("Goal progress must be between 0 and 100%.")
        start,due=_d(self.start_date),_d(self.due_date)
        if start and due and due < start: throw("Goal Due Date cannot precede Start Date.")
        if self.parent_goal:
            if self.parent_goal == self.name: throw("A goal cannot be aligned to itself.")
            parent=get_doc("Performance Goal",self.parent_goal,ignore_permissions=True)
            if parent.cycle != self.cycle: throw("Aligned parent and child goals must belong to the same Performance Cycle.")
            seen={self.name}; cursor=parent
            while cursor:
                if cursor.name in seen: throw("Goal alignment cannot contain a circular parent-child relationship.")
                seen.add(cursor.name)
                next_parent=getattr(cursor,"parent_goal",None)
                cursor=get_doc("Performance Goal",next_parent,ignore_permissions=True) if next_parent else None
        if self.target_value is not None and self.actual_value is not None and float(self.target_value or 0) != float(self.baseline or 0):
            calculated=(float(self.actual_value or 0)-float(self.baseline or 0))/(float(self.target_value)-float(self.baseline or 0))*100
            if calculated >= 0: self.progress_percent=min(100,round(calculated,2))
        if self.status == "Completed": self.progress_percent=100
