from velora import Document

from ....rules import validate_rule


class NotificationRule(Document):
    def validate(self):
        validate_rule(self)

    def on_update(self):
        from .... import engine
        engine.invalidate()

    def after_delete(self):
        from .... import engine
        engine.invalidate()
