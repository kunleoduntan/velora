from velora import Document, throw
class TrainingCourse(Document):
    def validate(self):
        if self.duration_hours is not None and float(self.duration_hours) < 0: throw("Duration cannot be negative.")
        if self.estimated_cost is not None and float(self.estimated_cost) < 0: throw("Estimated Cost cannot be negative.")
        if not self.course_code or not self.course_title: throw("Course Code and Course Title are required.")

