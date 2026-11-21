"""Control-plane tables. This database holds identity and routing ONLY - never business records."""
from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, JSON, MetaData, String, Table, Text, UniqueConstraint

cp_metadata = MetaData()

tenant = Table(
    "cp_tenant", cp_metadata,
    Column("id", String(20), primary_key=True),
    Column("name", String(200), nullable=False, unique=True),
    Column("status", String(20), nullable=False, default="active"),
    Column("created_on", DateTime),
)

company = Table(
    "cp_company", cp_metadata,
    Column("id", String(20), primary_key=True),
    Column("tenant_id", String(20), nullable=False, index=True),
    Column("name", String(200), nullable=False),
    Column("code", String(60), nullable=False, unique=True),
    Column("db_engine", String(20), nullable=False),          # postgres | sqlite
    Column("db_host", String(255)),
    Column("db_port", Integer),
    Column("db_name", String(500)),                           # sqlite: file path
    Column("db_user", String(120)),
    Column("secret_ref", String(255)),                        # reference to the credential - NEVER the password itself
    Column("provisioned_db", Boolean, default=False),         # True when Velora created (and may drop) the database
    Column("status", String(20), nullable=False, default="provisioning"),   # provisioning|active|suspended|failed
    Column("provisioning_status", String(60)),
    Column("provisioning_error", Text),
    Column("schema_version", String(40)),
    Column("created_on", DateTime),
    UniqueConstraint("tenant_id", "name", name="uq_cp_company_tenant_name"),
)

# A web address that belongs to ONE company (acme-erp.example.com -> COMP-001). Never shared data: only "which company does this address open".
domain = Table(
    "cp_domain", cp_metadata,
    Column("domain", String(253), primary_key=True),
    Column("company_id", String(40), nullable=False, index=True),
    Column("is_primary", Boolean, nullable=False, default=False),
    Column("locked", Boolean, nullable=False, default=True),       # True: people signed in on this address can only use THIS company
    Column("status", String(20), nullable=False, default="active"),
    Column("tls", Boolean, nullable=False, default=False),
    Column("created_on", DateTime),
)

user = Table(
    "cp_user", cp_metadata,
    Column("id", String(32), primary_key=True),
    Column("email", String(254), nullable=False, unique=True),
    Column("full_name", String(200)),
    Column("password_hash", String(400), nullable=False),
    Column("is_active", Boolean, nullable=False, default=True),
    Column("is_platform_admin", Boolean, nullable=False, default=False),
    Column("failed_attempts", Integer, nullable=False, default=0),
    Column("locked_until", DateTime),
    Column("created_on", DateTime),
    Column("last_login", DateTime),
    Column("totp_secret_ref", String(60)),
    Column("totp_pending_ref", String(60)),
    Column("totp_last_step", BigInteger),                       # the last accepted 30-second step: a code can be used once
    Column("totp_enabled", Boolean, nullable=False, default=False),
)

user_company = Table(
    "cp_user_company", cp_metadata,
    Column("user_id", String(32), primary_key=True),
    Column("company_id", String(20), primary_key=True),
    Column("roles", JSON, nullable=False),                    # legacy roles; new assignments are stored in the company database
    Column("granted_on", DateTime),
    Column("granted_by", String(254)),
)

session = Table(
    "cp_session", cp_metadata,
    Column("token_hash", String(64), primary_key=True),       # SHA-256 of the token; the token itself is never stored
    Column("user_id", String(32), nullable=False, index=True),
    Column("created_on", DateTime, nullable=False),
    Column("expires_on", DateTime, nullable=False),
    Column("last_seen", DateTime),
    Column("active_company_id", String(20)),
    Column("ip", String(64)),
    Column("user_agent", String(300)),
)

secret = Table(
    "cp_secret", cp_metadata,
    Column("ref", String(60), primary_key=True),
    Column("ciphertext", Text, nullable=False),               # Fernet-encrypted; the master key lives outside the database
    Column("created_on", DateTime),
)

audit = Table(
    "cp_audit", cp_metadata,
    Column("id", String(32), primary_key=True),
    Column("ts", DateTime, nullable=False, index=True),
    Column("actor", String(254)),
    Column("event", String(60), nullable=False, index=True),
    Column("subject", String(254)),
    Column("detail", JSON),
)

meta = Table(
    "cp_meta", cp_metadata,
    Column("key", String(60), primary_key=True),
    Column("value", String(255)),
)


login_ip = Table(
    "cp_login_ip", cp_metadata,
    Column("ip", String(64), primary_key=True),
    Column("window_started", DateTime, nullable=False),
    Column("attempts", Integer, nullable=False, default=0),
    Column("blocked_until", DateTime),
)
