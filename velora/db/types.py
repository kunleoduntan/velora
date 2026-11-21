"""Column types that differ by database."""
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB


def json_type():
    """JSON everywhere, but JSONB on PostgreSQL: stored decomposed (faster to read and query), indexable (GIN) and queryable (@>, ?).
    Trade-off: PostgreSQL normalises it (key order is not kept, duplicate keys collapse). Never use it for a payload whose exact bytes matter (e.g. a signed webhook body): store that as text."""
    return JSON().with_variant(JSONB(), "postgresql")
