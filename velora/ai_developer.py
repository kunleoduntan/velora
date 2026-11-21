"""Governed AI developer tools for metadata, code, database inspection and safe document actions.

AI output is treated as untrusted input. Generated artifacts are validated and returned as
reviewable drafts; code is never executed and arbitrary shell/SQL writes are never run.
Document mutations are limited to draft CRUD through the normal Document engine and require
a preview token plus explicit human confirmation.
"""
from __future__ import annotations

# Imported at MODULE level on purpose: with `from __future__ import annotations` FastAPI resolves the string annotation `Request`
# in this module's globals. Imported inside install_routes() it is unresolvable and `request` becomes a required query parameter (HTTP 422 on every route).
from fastapi import Body, Request

import ast
import json
import re
import secrets
import time
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, JSON, MetaData, String, Table, insert, select, update
from sqlalchemy import inspect as sa_inspect, text

from . import db
from .exceptions import PermissionDenied, ValidationError
from .permissions import get_session, _effective_roles, check_permission
from .meta.registry import registry
from .meta.spec import DocType
from .db.tables import table_name

md = MetaData()
agents = Table("vl_ai_agent", md,
    Column("id", String(32), primary_key=True), Column("agent_key", String(100), nullable=False, unique=True),
    Column("title", String(140), nullable=False), Column("description", String(500)),
    Column("instructions", String(12000), nullable=False), Column("roles", JSON, nullable=False),
    Column("tools", JSON, nullable=False), Column("enabled", String(8), nullable=False),
    Column("created_by", String(254), nullable=False), Column("created_on", DateTime, nullable=False),
    Column("modified_on", DateTime, nullable=False))

_PENDING: dict[str, dict] = {}
_TOKEN_TTL = 300
AI_DEV_LEVEL = 7  # 4=tool orchestration, 5=application builder, 6=migration assistant, 7=native provider tools
_ALLOWED_TOOLS = {"doctype.generate", "code.generate", "database.inspect", "database.query_readonly",
                  "document.create_draft", "document.update_draft", "document.delete_draft", "command.suggest"}
_DANGEROUS_SQL = re.compile(r"\b(insert|update|delete|merge|alter|drop|truncate|create|replace|grant|revoke|attach|detach|pragma|vacuum|call|execute|copy|load_extension|pg_sleep|dblink|readfile|writefile)\b", re.I)


def _ensure():
    from .db import extra_tables
    extra_tables.ensure(md)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _tools_available():
    if AI_DEV_LEVEL <= 1: return set()
    if AI_DEV_LEVEL == 2: return {"doctype.generate", "code.generate"}
    return set(_ALLOWED_TOOLS)


def _require_developer():
    s = get_session(); roles = set(_effective_roles(s))
    if s.user != "Administrator" and not roles.intersection({"System Manager", "AI Administrator", "Developer", "AI Developer"}):
        raise PermissionDenied("AI Developer Studio requires System Manager, AI Administrator or Developer role")


def _ai_answer(prompt: str, max_len: int = 30000) -> str:
    from . import ai
    result = ai.ask("general", prompt, timeout=60)
    answer = result.get("answer", "")
    if not isinstance(answer, str) or not answer.strip():
        raise ValidationError("The AI provider returned no usable content")
    return answer[:max_len]


def _strip_fence(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^```(?:json|python|javascript|typescript|sql)?\s*", "", value, flags=re.I)
    value = re.sub(r"\s*```$", "", value)
    return value.strip()


def generate_doctype(description: str, app: str, module: str, *, is_submittable: bool = False) -> dict:
    _require_developer()
    if not isinstance(description, str) or not description.strip() or len(description) > 8000:
        raise ValidationError("Describe the DocType in up to 8,000 characters")
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,79}", app or ""):
        raise ValidationError("App name must be a lowercase installed app identifier")
    if app not in registry.apps:
        raise ValidationError(f"App {app!r} is not installed in this site")
    if not isinstance(module, str) or not module.strip() or len(module) > 100:
        raise ValidationError("A module name is required")
    prompt = f'''You are generating a Velora DocType metadata JSON definition. Return ONLY one JSON object, no markdown.
Use spec_version 1; keys: name, module, app, autoname, title_field, is_submittable, istable=false, track_changes=true, description, fields, permissions.
Allowed fieldtype values: Data, Text, Int, Float, Currency, Check, Date, Datetime, Select, Link, JSON, Section Break, Column Break, Tab Break, Table.
Field names must be lowercase snake_case. Link/Table fields require options. Select options must be a JSON array. Include sensible role permissions with least privilege. Never add system fields such as name, owner, docstatus, creation or modified. Do not invent accounting posting logic. Do not create arbitrary code hooks.
Requested app: {app}; module: {module}; submittable: {bool(is_submittable)}.
Business requirement: {description.strip()}
'''
    raw = _strip_fence(_ai_answer(prompt))
    try: data = json.loads(raw)
    except Exception as exc: raise ValidationError("AI output was not valid JSON; refine the request and retry") from exc
    if not isinstance(data, dict): raise ValidationError("AI DocType output must be one JSON object")
    data["app"] = app; data["module"] = module.strip(); data["is_submittable"] = bool(is_submittable)
    # Normalize common AI omissions without weakening the framework validator.
    data.setdefault("track_changes", True)
    meta = DocType.from_dict(data, app=app, source="AI draft")
    normalized = meta.to_dict()
    normalized.update({"app": app, "module": module.strip(), "description": data.get("description", ""),
                       "permissions": data.get("permissions", []), "spec_version": 1})
    return {"valid": True, "doctype": normalized, "json": json.dumps(normalized, indent=2, ensure_ascii=False),
            "persisted": False, "next_step": "Review the JSON, then use the DocType Creator preview and create workflow."}


def generate_code(task: str, language: str = "python", target: str = "server") -> dict:
    _require_developer()
    if not isinstance(task, str) or not task.strip() or len(task) > 8000: raise ValidationError("Describe the code task in up to 8,000 characters")
    if language not in {"python", "javascript", "typescript", "sql"}: raise ValidationError("Supported languages: python, javascript, typescript, sql")
    if target not in {"server", "client", "test", "migration", "report"}: raise ValidationError("Unsupported code target")
    prompt = f'''Generate production-quality {language} code for a Velora metadata-driven ERP framework.
Target: {target}. Task: {task.strip()}
Return ONLY source code, without markdown fences. Prefer framework APIs and parameterized database access.
Never include secrets, credentials, arbitrary shell execution, eval/exec, destructive SQL, or code that bypasses permissions.
For database changes, generate a migration plan/code draft with backup and rollback considerations; do not execute it.
'''
    source = _strip_fence(_ai_answer(prompt))
    if not source or len(source) > 50000: raise ValidationError("Generated code is empty or exceeds 50,000 characters")
    warnings = []
    if language == "python":
        try: ast.parse(source)
        except SyntaxError as exc: raise ValidationError(f"Generated Python has a syntax error at line {exc.lineno}: {exc.msg}") from None
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.Exec,)) if hasattr(ast, "Exec") else False: warnings.append("legacy exec statement")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec", "compile"}:
                raise ValidationError("Generated code contains a prohibited dynamic execution call")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"system", "popen", "run", "Popen"}:
                warnings.append("Generated code references a process API; review manually and do not execute without security review")
    if language == "sql":
        if _DANGEROUS_SQL.search(source): raise ValidationError("Generated SQL contains a mutating or unsafe operation; request a read-only query or migration explanation")
        if not re.match(r"^\s*select\b", source, re.I): raise ValidationError("Only read-only SELECT SQL can be generated for immediate review")
    return {"language": language, "target": target, "source": source, "syntax_validated": language == "python",
            "warnings": warnings, "executed": False, "persisted": False,
            "notice": "This is an untrusted draft. Review, test and approve it before adding it to an application."}


def inspect_database() -> dict:
    _require_developer()
    engine = db.get_engine(); inspector = sa_inspect(engine)
    known = {table_name(m.name): m.name for m in registry.all()}
    tables = []
    for physical, doctype in sorted(known.items()):
        if inspector.has_table(physical):
            tables.append({"table": physical, "doctype": doctype,
                           "columns": [{"name": c["name"], "type": str(c["type"]), "nullable": c.get("nullable", True)} for c in inspector.get_columns(physical)]})
    return {"dialect": engine.dialect.name, "tables": tables, "read_only": True}


def query_database(doctype: str, fields: list | None = None, filters=None, limit: int = 100, order_by: str | None = None) -> dict:
    """Read business data through the permission-aware document query engine, never raw SQL."""
    _require_developer()
    from .document import get_list
    if not isinstance(doctype, str) or not doctype.strip():
        raise ValidationError("doctype must be the name of a DocType")
    meta = registry.get(doctype)
    if meta.istable: raise ValidationError("Query the parent DocType rather than a child table directly")
    if fields is not None and (not isinstance(fields, list) or len(fields) > 30 or not all(isinstance(x, str) for x in fields)):
        raise ValidationError("fields must be a list of at most 30 field names")
    if filters is not None and not isinstance(filters, (dict, list)):
        raise ValidationError("filters must be an object or a list of [field, operator, value]")
    if isinstance(filters, dict) and not all(isinstance(k, str) for k in filters):
        raise ValidationError("filter names must be text")
    if isinstance(filters, list) and not all(
            isinstance(f, (list, tuple)) and len(f) in (3, 4) and isinstance(f[len(f) - 3], str) and isinstance(f[len(f) - 2], str) for f in filters):
        raise ValidationError("every filter must be [field, operator, value] with a text field and operator")
    if order_by is not None and not isinstance(order_by, str):
        raise ValidationError("order_by must be text")
    try:
        limit = max(1, min(int(limit), 200))
    except (TypeError, ValueError, OverflowError):
        raise ValidationError("limit must be a whole number") from None
    rows = get_list(doctype, filters=filters, fields=fields, order_by=order_by, limit=limit + 1)
    truncated = len(rows) > limit
    rows = rows[:limit]
    return {"doctype": doctype, "columns": list(rows[0].keys()) if rows else (fields or []),
            "rows": rows, "row_count": len(rows), "truncated": truncated,
            "read_only": True, "permission_checked": True}


def preview_document_operation(operation: str, doctype: str, values: dict | None = None, name: str | None = None, reason: str = "") -> dict:
    _require_developer()
    from .document import get_doc, new_doc
    if operation not in {"create_draft", "update_draft", "delete_draft"}: raise ValidationError("Only create_draft, update_draft and delete_draft are available to AI tools")
    if not isinstance(values or {}, dict) or len(values or {}) > 100: raise ValidationError("Document values must be an object with at most 100 fields")
    meta = registry.get(doctype)
    if meta.istable: raise ValidationError("AI document actions cannot operate directly on child DocTypes")
    if operation == "create_draft":
        doc = new_doc(doctype, **(values or {})); doc._check_perm("create")
        if doc.meta.is_submittable: doc.docstatus = 0
        field_names = list((values or {}).keys())
    else:
        if not name: raise ValidationError("A document name is required")
        doc = get_doc(doctype, name); doc._check_perm("write" if operation == "update_draft" else "delete")
        if int(doc.docstatus or 0) != 0: raise ValidationError("AI actions are limited to draft documents; submitted/cancelled documents are never changed or deleted")
        if operation == "update_draft":
            doc.update(values or {}); field_names = list((values or {}).keys())
        else: field_names = []
    token = secrets.token_urlsafe(32); actor = get_session().user
    _PENDING[token] = {"operation": operation, "doctype": doctype, "name": name, "values": values or {},
                       "reason": str(reason or "AI-assisted draft operation")[:500], "actor": actor,
                       "expires": time.time() + _TOKEN_TTL}
    return {"confirmation_token": token, "expires_in_seconds": _TOKEN_TTL, "operation": operation,
            "doctype": doctype, "document": name, "affected_fields": field_names,
            "requires_human_confirmation": True, "will_submit": False, "will_post": False}


def execute_document_operation(confirmation_token: str, confirm: bool) -> dict:
    _require_developer()
    if confirm is not True: raise PermissionDenied("Explicit confirmation is required")
    token = str(confirmation_token)
    plan = _PENDING.get(token)
    if not plan or plan["expires"] < time.time():
        _PENDING.pop(token, None)
        raise ValidationError("Confirmation token is invalid, expired or already used; preview the operation again")
    if plan["actor"] != get_session().user: raise PermissionDenied("Only the user who previewed the operation may confirm it")
    # Consume only after actor and expiry checks; failed attempts by another actor must not invalidate the owner's token.
    _PENDING.pop(token, None)
    from .document import get_doc, new_doc
    op, dt, name, values = plan["operation"], plan["doctype"], plan["name"], plan["values"]
    if op == "create_draft":
        doc = new_doc(dt, **values); doc.insert(); result_name = doc.name
    elif op == "update_draft":
        doc = get_doc(dt, name)
        if int(doc.docstatus or 0) != 0: raise ValidationError("Document is no longer a draft")
        doc.update(values); doc.save(); result_name = doc.name
    else:
        doc = get_doc(dt, name)
        if int(doc.docstatus or 0) != 0: raise ValidationError("Only drafts may be deleted")
        doc.delete(reason=plan["reason"]); result_name = name
    return {"completed": True, "operation": op, "doctype": dt, "document": result_name,
            "docstatus": 0 if op != "delete_draft" else None, "submitted": False, "posted": False}


def suggest_commands(task: str) -> dict:
    _require_developer()
    if not isinstance(task, str) or not task.strip() or len(task) > 4000: raise ValidationError("Describe the command you need")
    # The model may explain the safe command catalogue, but cannot introduce arbitrary shell commands.
    catalogue = [
        ("Inspect installation", "velora doctor"),
        ("List DocTypes", "velora doctypes"),
        ("Preview migration", "velora migrate --dry-run"),
        ("Run migration", "velora migrate"),
        ("Create backup", "velora backup"),
        ("List installed apps", "velora list-apps"),
        ("Check optional dependencies", "velora deps check"),
    ]
    prompt = "User task: " + task.strip() + "\nChoose only from this approved command catalogue. Return JSON with explanation and selected exact command(s). Never invent shell operators, sudo, rm, drop, purge, pipes, redirects or arbitrary scripts. Catalogue: " + json.dumps(catalogue)
    raw = _strip_fence(_ai_answer(prompt, 10000))
    try: data = json.loads(raw)
    except Exception: data = {"explanation": "Use the closest approved Velora CLI command. The AI response was not structured; review the catalogue.", "commands": []}
    approved = {cmd for _, cmd in catalogue}
    commands = [c for c in data.get("commands", []) if c in approved] if isinstance(data, dict) else []
    return {"explanation": str(data.get("explanation", ""))[:2000], "commands": commands,
            "catalogue": [{"label": label, "command": cmd} for label, cmd in catalogue],
            "executed": False, "notice": "Commands are suggestions only. Review the target workspace and backup before running them."}


def save_agent(payload: dict) -> dict:
    _require_developer(); _ensure()
    if not isinstance(payload, dict): raise ValidationError("Agent definition must be an object")
    key = str(payload.get("agent_key") or "").strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_.-]{1,79}", key): raise ValidationError("Agent key must be a lowercase stable identifier")
    title = str(payload.get("title") or "").strip(); instructions = str(payload.get("instructions") or "").strip()
    if not title or len(title) > 140 or not instructions or len(instructions) > 12000: raise ValidationError("Agent title and instructions are required; instructions max 12,000 characters")
    roles = payload.get("roles") or ["AI Developer"]
    tools = payload.get("tools") or []
    if not isinstance(roles, list) or len(roles) > 30 or not all(isinstance(x, str) and len(x) <= 80 for x in roles): raise ValidationError("Invalid agent role list")
    if not isinstance(tools, list) or len(tools) > 20 or not all(isinstance(x, str) for x in tools) or not set(tools).issubset(_tools_available()): raise ValidationError("Agent contains a tool not enabled in this release or an unsupported tool identifier")
    rid = str(payload.get("id") or secrets.token_hex(16)); now = _now(); actor = get_session().user
    row = {"id": rid, "agent_key": key, "title": title, "description": str(payload.get("description") or "")[:500],
           "instructions": instructions, "roles": roles, "tools": tools, "enabled": "1" if payload.get("enabled", True) else "0",
           "created_by": actor, "created_on": now, "modified_on": now}
    with db.transaction() as c:
        old = c.execute(select(agents.c.id).where(agents.c.agent_key == key)).first()
        if old:
            c.execute(update(agents).where(agents.c.agent_key == key).values(**{k:v for k,v in row.items() if k not in {"id", "created_by", "created_on"}}))
            rid = old[0]
        else: c.execute(insert(agents).values(**row))
    return {"id": rid, "agent_key": key, "title": title, "tools": tools, "roles": roles, "enabled": bool(payload.get("enabled", True))}


def list_agents() -> list[dict]:
    _ensure(); s = get_session(); roles = set(_effective_roles(s))
    with db.transaction() as c: rows = c.execute(select(agents).where(agents.c.enabled == "1").order_by(agents.c.title)).mappings().all()
    return [{"id":r["id"], "agent_key":r["agent_key"], "title":r["title"], "description":r["description"],
             "tools":r["tools"], "roles":r["roles"]} for r in rows if s.user == "Administrator" or not r["roles"] or roles.intersection(r["roles"])]


def run_agent(agent_key: str, question: str) -> dict:
    _ensure(); s = get_session(); roles = set(_effective_roles(s))
    with db.transaction() as c: row = c.execute(select(agents).where(agents.c.agent_key == agent_key, agents.c.enabled == "1")).mappings().first()
    if not row: raise ValidationError("AI agent is not available")
    if s.user != "Administrator" and row["roles"] and not roles.intersection(row["roles"]): raise PermissionDenied("You do not have access to this AI agent")
    if not isinstance(question, str) or not question.strip() or len(question) > 12000: raise ValidationError("Ask a question up to 12,000 characters")
    from . import ai
    advisor_id = "agent." + row["agent_key"]
    ai.register_advisor({"id": advisor_id, "title": row["title"], "description": row["description"],
                         "system_prompt": row["instructions"] + "\nYou may describe available tools but cannot execute tools unless a separate governed endpoint is explicitly invoked. Never claim to have performed an action.",
                         "roles": row["roles"]})
    result = ai.ask(advisor_id, question)
    return result | {"available_tools": row["tools"], "tools_executed": False}


def publish_doctype(definition: dict, app: str, module: str, on_conflict: str = "error") -> dict:
    _require_developer()
    from . import site as site_mod
    if not site_mod.current().developer_mode:
        raise PermissionDenied("Publishing AI-generated DocTypes requires developer mode")
    if not isinstance(definition, dict): raise ValidationError("DocType definition must be a JSON object")
    from .devtools import creator
    plan = creator.plan(definition, app=app, module=module, on_conflict=on_conflict)
    report = plan.report()
    if not report["ok"]: return {"created": [], "preview": report}
    created = creator.create(plan)
    # Reload metadata so the new DocType becomes visible in this running site.
    site_mod.current().load()
    return {"created": created.get("created", []), "files": created.get("files", []),
            "warnings": created.get("warnings", []), "preview": report}


def install_routes(app, run):
    @app.get("/api/ai/developer/tools")
    def tools(request: Request):
        def fn():
            _require_developer()
            return {"tools": sorted(_tools_available()), "can_develop": True, "level": AI_DEV_LEVEL}
        return run(request, fn)
    @app.get("/api/ai/agents")
    def agents_list(request: Request): return run(request, list_agents)
    @app.post("/api/ai/agents")
    def agents_save(request: Request, body: dict = Body(...)): return run(request, lambda: save_agent(body))
    @app.post("/api/ai/agents/{agent_key}/run")
    def agents_run(agent_key: str, request: Request, body: dict = Body(...)):
        return run(request, lambda: run_agent(agent_key, body.get("question", "")))

    if AI_DEV_LEVEL >= 2:
        @app.post("/api/ai/developer/doctype/generate")
        def doctype_generate(request: Request, body: dict = Body(...)):
            return run(request, lambda: generate_doctype(body.get("description", ""), body.get("app", ""), body.get("module", ""), is_submittable=body.get("is_submittable", False)))
        @app.post("/api/ai/developer/doctype/publish")
        def doctype_publish(request: Request, body: dict = Body(...)):
            return run(request, lambda: publish_doctype(body.get("definition", {}), body.get("app", ""), body.get("module", ""), body.get("on_conflict", "error")))
        @app.post("/api/ai/developer/code/generate")
        def code_generate(request: Request, body: dict = Body(...)):
            return run(request, lambda: generate_code(body.get("task", ""), body.get("language", "python"), body.get("target", "server")))

    if AI_DEV_LEVEL >= 3:
        @app.get("/api/ai/developer/database")
        def database(request: Request): return run(request, inspect_database)
        @app.post("/api/ai/developer/database/query")
        def database_query(request: Request, body: dict = Body(...)):
            return run(request, lambda: query_database(body.get("doctype", ""), body.get("fields"), body.get("filters"), body.get("limit", 100), body.get("order_by")))
        @app.post("/api/ai/developer/document/preview")
        def document_preview(request: Request, body: dict = Body(...)):
            return run(request, lambda: preview_document_operation(body.get("operation", ""), body.get("doctype", ""), body.get("values"), body.get("name"), body.get("reason", "")))
        @app.post("/api/ai/developer/document/execute")
        def document_execute(request: Request, body: dict = Body(...)):
            return run(request, lambda: execute_document_operation(body.get("confirmation_token", ""), body.get("confirm") is True))
        @app.post("/api/ai/developer/commands/suggest")
        def commands(request: Request, body: dict = Body(...)):
            return run(request, lambda: suggest_commands(body.get("task", "")))

    if AI_DEV_LEVEL >= 4:
        from .ai_tool_engine import install_routes as install_ai_tool_routes
        install_ai_tool_routes(app, run)
    if AI_DEV_LEVEL >= 5:
        from .ai_app_builder import install_routes as install_ai_app_builder_routes
        install_ai_app_builder_routes(app, run)
    if AI_DEV_LEVEL >= 6:
        from .ai_migrations import install_routes as install_ai_migration_routes
        install_ai_migration_routes(app, run)
