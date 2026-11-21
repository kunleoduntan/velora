"""Framework-owned tables (not DocType-driven)."""
from sqlalchemy import Boolean, Column, DateTime, Integer, MetaData, String, Table, UniqueConstraint

from .types import json_type

system_metadata = MetaData()

# Naming-series counters. Row-locked by UPDATE, so concurrent inserts serialise.
series = Table(
    "velora_series", system_metadata,
    Column("name", String(140), primary_key=True),
    Column("current", Integer, nullable=False, default=0),
)

# Audit trail written when a DocType has track_changes enabled.
version = Table(
    "velora_version", system_metadata,
    Column("name", String(40), primary_key=True),
    Column("ref_doctype", String(140), index=True),
    Column("docname", String(255), index=True),
    Column("data", json_type()),
    Column("owner", String(140)),
    Column("creation", DateTime),
)

# Every spreadsheet export is recorded (who, what, how many rows) - exports are the main data-leak path.
export_log = Table(
    "velora_export_log", system_metadata,
    Column("name", String(40), primary_key=True),
    Column("ref_doctype", String(140), index=True),
    Column("owner", String(140)),
    Column("creation", DateTime),
    Column("scope", String(20)),
    Column("row_count", Integer),
    Column("detail", json_type()),
)

# Which apps are installed on THIS site (each site has its own database, hence its own list).
installed_app = Table(
    "velora_installed_app", system_metadata,
    Column("name", String(140), primary_key=True),
    Column("version", String(40)),
    Column("installed_on", DateTime),
)

# Per-site / per-company framework settings (theme, branding ...): small JSON values keyed by name.
setting = Table(
    "velora_setting", system_metadata,
    Column("key", String(140), primary_key=True),
    Column("value", json_type()),
    Column("updated_by", String(254)),
    Column("updated_on", DateTime),
)

# Reports built in the report builder and saved by a person (optionally shared with everyone in the company).
# Only the DEFINITION is stored: whoever runs it sees what THEY are allowed to see.
saved_report = Table(
    "velora_saved_report", system_metadata,
    Column("id", String(24), primary_key=True),
    Column("name", String(100), nullable=False),
    Column("owner", String(254), nullable=False, index=True),
    Column("doctype", String(140), nullable=False, index=True),
    Column("spec", json_type(), nullable=False),
    Column("shared", Boolean, nullable=False, default=False),
    Column("created_on", DateTime),
    Column("updated_on", DateTime),
    UniqueConstraint("owner", "name", name="uq_saved_report_owner_name"),
)

# Data patches that have already run against THIS database (each runs exactly once).
patch_log = Table(
    "velora_patch_log", system_metadata,
    Column("patch", String(255), primary_key=True),
    Column("ran_on", DateTime),
)

# When each scheduled frequency last ran in THIS database (so several workers never run the same job twice).
scheduler_state = Table(
    "velora_scheduler_state", system_metadata,
    Column("key", String(60), primary_key=True),
    Column("last_run", DateTime),
    Column("owner", String(80)),
)

# PostgreSQL-only objects (triggers, constraints, indexes ...) that apps declare in hooks.py `pg_objects`: what has been applied here, and a checksum of it.
pg_object = Table(
    "velora_pg_object", system_metadata,
    Column("name", String(120), primary_key=True),
    Column("app", String(80)),
    Column("checksum", String(64), nullable=False),
    Column("applied_on", DateTime),
)

# Membership roles live in the company database. The Control Plane stores only the
# identity-to-company membership needed for routing; this table is authoritative for roles.
from .types import json_type as _json_type
company_user_role = Table(
    "velora_company_user_role", system_metadata,
    Column("user_email", String(254), primary_key=True),
    Column("roles", _json_type(), nullable=False),
    Column("granted_by", String(254)),
    Column("granted_on", DateTime),
)

# Per-record sharing (company-local). A share never crosses company databases.
doc_share = Table(
    "velora_doc_share", system_metadata,
    Column("doctype", String(140), primary_key=True),
    Column("docname", String(255), primary_key=True),
    Column("user_email", String(254), primary_key=True),
    Column("read", Boolean, nullable=False, default=True),
    Column("write", Boolean, nullable=False, default=False),
    Column("granted_by", String(254)),
    Column("granted_on", DateTime),
)

# Company-local RBAC catalog (v0.36). These tables are installed in each
# company database, never in the central control plane.
role_definition = Table(
    "velora_role_definition", system_metadata,
    Column("name", String(120), primary_key=True),
    Column("description", String(500), nullable=False, default=""),
    Column("is_system", Boolean, nullable=False, default=False),
    Column("is_active", Boolean, nullable=False, default=True),
    Column("created_by", String(254)),
    Column("created_on", DateTime),
)
role_inheritance = Table(
    "velora_role_inheritance", system_metadata,
    Column("role", String(120), primary_key=True),
    Column("inherits_role", String(120), primary_key=True),
)
role_permission = Table(
    "velora_role_permission", system_metadata,
    Column("role", String(120), primary_key=True),
    Column("doctype", String(140), primary_key=True),
    Column("permission", String(20), primary_key=True),
    Column("allowed", Boolean, nullable=False, default=True),
)
role_field_permission = Table(
    "velora_role_field_permission", system_metadata,
    Column("role", String(120), primary_key=True),
    Column("doctype", String(140), primary_key=True),
    Column("fieldname", String(140), primary_key=True),
    Column("access", String(20), nullable=False),
)

# Enterprise segregation-of-duties role conflicts (v1.4). Pairs are unordered.
role_conflict = Table(
    "velora_role_conflict", system_metadata,
    Column("role_a", String(120), primary_key=True),
    Column("role_b", String(120), primary_key=True),
    Column("reason", String(500), nullable=False, default=""),
    Column("created_by", String(254)),
    Column("created_on", DateTime),
)


# Company-local row-level security policies (v0.38). Conditions are structured
# JSON, never SQL fragments or executable expressions.
row_policy = Table(
    "velora_row_policy", system_metadata,
    Column("role", String(120), primary_key=True),
    Column("doctype", String(140), primary_key=True),
    Column("permission", String(20), primary_key=True),
    Column("conditions", json_type(), nullable=False),
    Column("is_active", Boolean, nullable=False, default=True),
    Column("updated_by", String(254)),
    Column("updated_on", DateTime),
)
