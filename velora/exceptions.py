"""Framework exception hierarchy. The API layer maps `status_code` to HTTP."""


class VeloraError(Exception):
    status_code = 500

    def __init__(self, message: str = "", *, details=None, advice=None):
        super().__init__(message)
        self.details = details
        self.advice = advice                      # {"hint": ..., "actions": [{"label", "href"}], "field": ...}: what to do next


class MetaError(VeloraError):
    """Invalid or inconsistent DocType metadata."""


class ValidationError(VeloraError):
    status_code = 422


class MandatoryError(ValidationError):
    pass


class LinkValidationError(ValidationError):
    pass


class DocStatusError(ValidationError):
    pass


class LinkedDocumentsError(ValidationError):
    """A document cannot be cancelled while submitted documents depend on it. `blockers` lists them: [{"doctype", "name"}]."""

    def __init__(self, message: str, blockers: list[dict] | None = None):
        super().__init__(message)
        self.blockers = blockers or []


class AuthenticationRequired(VeloraError):
    status_code = 401


class PermissionDenied(VeloraError):
    status_code = 403


class DoesNotExistError(VeloraError):
    status_code = 404


class DuplicateEntryError(VeloraError):
    status_code = 409


class TimestampMismatchError(VeloraError):
    """Document was modified by someone else after it was loaded."""
    status_code = 409


class CompanyAccessDenied(PermissionDenied):
    """Deliberately the same message for 'no such company' and 'not yours' - never reveals which companies exist."""


class CompanyUnavailable(VeloraError):
    status_code = 423


class ServiceUnavailable(VeloraError):
    status_code = 503


class Maintenance(VeloraError):
    status_code = 503


class UpgradePending(VeloraError):
    """The code is newer than this database. Run `velora upgrade`."""
    status_code = 503


class PatchError(VeloraError):
    status_code = 500
