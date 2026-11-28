"""Company-local Server Scripts and Client Scripts.

Server scripts execute in a deliberately small AST-allowlisted Python subset.
Client scripts execute in the authenticated browser session and therefore remain
trusted company customizations; they are never an authorization boundary.
"""
from __future__ import annotations
import ast
import copy
import re
import secrets
import weakref
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, Text, UniqueConstraint, delete, insert, select, update, inspect
from fastapi import Body, Request
from . import db
from .exceptions import DoesNotExistError, PermissionDenied, ValidationError
from .permissions import get_session

md = MetaData()
_ensured_engines = weakref.WeakSet()
_table_known = weakref.WeakSet()
scripts = Table('vl_custom_script', md,
    Column('id', String(32), primary_key=True),
    Column('script_type', String(16), nullable=False),
    Column('name', String(140), nullable=False),
    Column('doctype', String(140), nullable=False),
    Column('event', String(40), nullable=False),
    Column('code', Text, nullable=False),
    Column('source_code', Text),
    Column('language', String(20), nullable=False, default='python'),
    Column('enabled', Integer, nullable=False, default=1),
    Column('version', Integer, nullable=False, default=1),
    Column('created_by', String(254)), Column('modified_by', String(254)),
    Column('created_on', DateTime), Column('modified_on', DateTime),
    UniqueConstraint('script_type', 'name', name='uq_vl_custom_script_type_name'))

script_versions = Table('vl_custom_script_version', md,
    Column('id', String(32), primary_key=True), Column('script_id', String(32), nullable=False),
    Column('version', Integer, nullable=False), Column('script_type', String(16), nullable=False),
    Column('name', String(140), nullable=False), Column('doctype', String(140), nullable=False),
    Column('event', String(40), nullable=False), Column('language', String(20), nullable=False),
    Column('code', Text, nullable=False), Column('source_code', Text), Column('enabled', Integer, nullable=False),
    Column('created_by', String(254)), Column('created_on', DateTime),
    UniqueConstraint('script_id', 'version', name='uq_vl_custom_script_version'))

SERVER_EVENTS = {'before_insert','after_insert','before_validate','validate','before_save','on_update','after_save',
                 'before_submit','on_submit','before_cancel','on_cancel','before_delete','after_delete'}
CLIENT_EVENTS = {'form','list'}
MAX_CODE = 100_000

def _now(): return datetime.now(timezone.utc).replace(tzinfo=None)
def ensure(engine=None):
    engine=engine or db.get_engine()
    if engine not in _ensured_engines:                        # (it used to run a catalog query on EVERY call: `engine not in set or not has_table`)
        md.create_all(engine)
        # Additive upgrade for databases created by v0.18 and earlier.
        cols={c['name'] for c in inspect(engine).get_columns('vl_custom_script')}
        with engine.begin() as conn:
            if 'source_code' not in cols: conn.exec_driver_sql('ALTER TABLE vl_custom_script ADD COLUMN source_code TEXT')
            if 'language' not in cols: conn.exec_driver_sql("ALTER TABLE vl_custom_script ADD COLUMN language VARCHAR(20) NOT NULL DEFAULT 'python'")
            conn.exec_driver_sql("UPDATE vl_custom_script SET language='javascript' WHERE script_type='client' AND language='python'")
        _ensured_engines.add(engine)
def _admin():
    s=get_session()
    if s.user != 'Administrator' and 'System Manager' not in s.roles:
        raise PermissionDenied('Only a System Manager can manage custom scripts')
    return s

def _validate(data, existing=None):
    existing=existing or {}
    kind=str(data.get('script_type') or existing.get('script_type') or '').lower()
    name=str(data.get('name') or existing.get('name') or '').strip()
    doctype=str(data.get('doctype') or existing.get('doctype') or '').strip()
    event=str(data.get('event') or existing.get('event') or '').strip()
    language=str(data.get('language') or existing.get('language') or ('python' if kind=='server' else 'javascript')).lower()
    code=data.get('code', existing.get('code', ''))
    source_code=data.get('source_code', existing.get('source_code') or code)
    if kind not in {'server','client'}: raise ValidationError('script_type must be server or client')
    if not name or len(name)>140: raise ValidationError('Script name is required (maximum 140 characters)')
    if not doctype: raise ValidationError('A DocType is required')
    from .meta.registry import registry
    registry.get(doctype)
    allowed=SERVER_EVENTS if kind=='server' else CLIENT_EVENTS
    if event not in allowed: raise ValidationError(f'Unsupported {kind} script event: {event}')
    if kind=='server' and language!='python': raise ValidationError('Server Scripts must use Python')
    if kind=='client' and language not in {'javascript','typescript'}: raise ValidationError('Client Scripts must use JavaScript or TypeScript')
    if not isinstance(code,str) or not code.strip() or len(code)>MAX_CODE: raise ValidationError('Compiled script code is required and must not exceed 100 KB')
    if not isinstance(source_code,str) or not source_code.strip() or len(source_code)>MAX_CODE: raise ValidationError('Script source is required and must not exceed 100 KB')
    if kind=='server':
        _compile_server_script(code, name)
    return {'script_type':kind,'name':name,'doctype':doctype,'event':event,'language':language,'code':code,'source_code':source_code}

def list_scripts(script_type=None, doctype=None):
    ensure(); _admin(); stmt=select(scripts)
    if script_type: stmt=stmt.where(scripts.c.script_type==script_type)
    if doctype: stmt=stmt.where(scripts.c.doctype==doctype)
    with db.transaction() as c: return [dict(r) for r in c.execute(stmt.order_by(scripts.c.script_type,scripts.c.doctype,scripts.c.name)).mappings()]

def save_script(data):
    s=_admin(); ensure(); values=_validate(data); at=_now()
    with db.transaction() as c:
        old=c.execute(select(scripts).where(scripts.c.script_type==values['script_type'],scripts.c.name==values['name'])).mappings().first()
        if old:
            rid=old['id']; version=old['version']+1
        else:
            rid=secrets.token_hex(16); version=1
        enabled=int(bool(data.get('enabled',True)))
        c.execute(insert(script_versions).values(id=secrets.token_hex(16),script_id=rid,version=version,
            script_type=values['script_type'],name=values['name'],doctype=values['doctype'],event=values['event'],
            language=values['language'],code=values['code'],source_code=values['source_code'],enabled=enabled,
            created_by=s.user,created_on=at))
        if old:
            c.execute(update(scripts).where(scripts.c.id==rid).values(**values,enabled=enabled,version=version,modified_by=s.user,modified_on=at))
        else:
            c.execute(insert(scripts).values(id=rid,**values,enabled=enabled,version=version,created_by=s.user,modified_by=s.user,created_on=at,modified_on=at))
    return {'id':rid,**values,'enabled':bool(enabled),'version':version}

def script_history(script_id):
    ensure(); _admin()
    with db.transaction() as c:
        if not c.execute(select(scripts.c.id).where(scripts.c.id==script_id)).first(): raise DoesNotExistError('Custom script not found')
        rows=c.execute(select(script_versions).where(script_versions.c.script_id==script_id).order_by(script_versions.c.version.desc())).mappings().all()
    return [dict(r) for r in rows]

def restore_script(script_id, version):
    _admin(); ensure()
    with db.transaction() as c:
        row=c.execute(select(script_versions).where(script_versions.c.script_id==script_id,script_versions.c.version==version)).mappings().first()
    if not row: raise DoesNotExistError('Script version not found')
    return save_script({'script_type':row['script_type'],'name':row['name'],'doctype':row['doctype'],'event':row['event'],
        'language':row['language'],'code':row['code'],'source_code':row['source_code'],'enabled':bool(row['enabled'])})

def validate_script(data):
    _admin(); values=_validate(data)
    return {'valid':True,'script_type':values['script_type'],'language':values['language'],'doctype':values['doctype'],'event':values['event']}

def delete_script(script_id):
    _admin(); ensure()
    with db.transaction() as c:
        result=c.execute(delete(scripts).where(scripts.c.id==script_id))
        if not result.rowcount: raise DoesNotExistError('Custom script not found')
        c.execute(delete(script_versions).where(script_versions.c.script_id==script_id))
    return {'deleted':True,'id':script_id}

def client_code(doctype, kind):
    ensure()
    if kind not in {'form','list'}: raise ValidationError('Client script kind must be form or list')
    event=kind
    with db.transaction() as c:
        rows=c.execute(select(scripts.c.code).where(scripts.c.script_type=='client',scripts.c.doctype==doctype,scripts.c.enabled==1,
            scripts.c.event==event).order_by(scripts.c.name)).scalars().all()
    return '\n;\n'.join(rows)

class _DocProxy:
    __slots__=('_doc','_allowed','_writable')
    def __init__(self, doc):
        object.__setattr__(self,'_doc',doc); object.__setattr__(self,'_allowed',set(doc.meta.column_names()))
        object.__setattr__(self,'_writable',{f.fieldname for f in doc.meta.value_fields})   # NOT docstatus/owner/name/creation/modified: a script must not bypass submit, ownership or naming
    def __getattr__(self,name):
        if name in self._allowed: return self._doc.get(name)
        if name=='doctype': return self._doc.doctype
        if name=='name': return self._doc.name
        raise AttributeError(name)
    def __setattr__(self,name,value):
        if name not in self._writable: raise AttributeError(f'Field {name!r} is not writable')
        self._doc.set(name,value)
    def get(self,name,default=None):
        if name not in self._allowed: return default
        return self._doc.get(name,default)
    def set(self,name,value): setattr(self,name,value)
    def as_dict(self): return self._doc.as_dict()

def _write_guard(obj):
    if not isinstance(obj,_DocProxy): raise TypeError('Server Script cannot modify this object')
    return obj

MAX_SEQUENCE = 100_000          # longest string/list a script may build
MAX_BITS = 4096                 # largest whole number (about 1,200 digits)
MAX_RANGE = 10_000              # longest range(): sum(range(10**12)) is ONE C call that nothing can interrupt, so it must never start

def _check_size(value):
    if isinstance(value, int) and not isinstance(value, bool) and value.bit_length() > MAX_BITS:
        raise ValidationError('Server Script produced a number that is too large')
    if isinstance(value, (str, bytes, list, tuple, set, dict)) and len(value) > MAX_SEQUENCE:
        raise ValidationError('Server Script produced a value that is too large')
    return value

def _vl_add(a, b): return _check_size(a + b)                      # repeated x = x + x doubles a string each line

def _vl_mul(a, b):
    for seq, n in ((a, b), (b, a)):
        if isinstance(seq, (str, bytes, list, tuple)) and isinstance(n, int) and n > 0 and len(seq) * n > MAX_SEQUENCE:
            raise ValidationError('Server Script would build a value that is too large')   # refused BEFORE it is allocated
    return _check_size(a * b)

_FORMAT_SPEC = re.compile(r'%[^a-zA-Z%]*[a-zA-Z]')
def _vl_mod(a, b):
    if isinstance(a, str):
        for spec in _FORMAT_SPEC.findall(a):
            if '*' in spec or any(int(n) > 1000 for n in re.findall(r'\d+', spec)):
                raise ValidationError("Server Script uses a text-format width that is too large")   # '%999999999d' % 1 allocates a gigabyte
    return _check_size(a % b)

def _vl_range(*args):
    r = range(*args)
    if len(r) > MAX_RANGE: raise ValidationError(f'range() may produce at most {MAX_RANGE:,} numbers in a Server Script')
    return r

_SCRIPT_BUILTINS = {
    "str": str, "int": int, "float": float, "bool": bool, "len": len,
    "min": min, "max": max, "round": round, "abs": abs, "sum": sum,
    "all": all, "any": any, "enumerate": enumerate, "range": _vl_range,
}
_GUARDED_OPS = {ast.Add: '_vl_add', ast.Mult: '_vl_mul', ast.Mod: '_vl_mod'}

class _SizeGuard(ast.NodeTransformer):
    """Rewrites a VALIDATED script so every + * % goes through a size check (the validator forbids user code from naming these helpers: names starting with _ are refused)."""
    def visit_BinOp(self, node):
        self.generic_visit(node)
        fn = _GUARDED_OPS.get(type(node.op))
        if not fn: return node
        return ast.copy_location(ast.Call(func=ast.Name(fn, ast.Load()), args=[node.left, node.right], keywords=[]), node)
    def visit_AugAssign(self, node):
        self.generic_visit(node)
        fn = _GUARDED_OPS.get(type(node.op))
        if not fn: return node
        current = copy.deepcopy(node.target); current.ctx = ast.Load()
        call = ast.Call(func=ast.Name(fn, ast.Load()), args=[current, node.value], keywords=[])
        return ast.copy_location(ast.Assign(targets=[node.target], value=call), node)
_SCRIPT_NODES = (
    ast.Module, ast.Expr, ast.If, ast.Assign, ast.AugAssign, ast.Name, ast.Load, ast.Store,
    ast.Attribute, ast.Constant, ast.Compare, ast.BinOp, ast.BoolOp, ast.UnaryOp, ast.Call,
    ast.List, ast.Tuple, ast.Dict, ast.Set, ast.Subscript, ast.IfExp, ast.keyword,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is, ast.IsNot,
    ast.And, ast.Or, ast.Not, ast.UAdd, ast.USub,
)

class _ServerScriptValidator(ast.NodeVisitor):
    """Small, deliberately non-Turing-complete Python subset for company scripts."""
    def __init__(self): self.errors = []
    def generic_visit(self, node):
        if not isinstance(node, _SCRIPT_NODES):
            self.errors.append(f"{type(node).__name__} is not permitted")
            return
        super().generic_visit(node)
    def visit_Attribute(self, node):
        if not isinstance(node.value, ast.Name) or node.value.id != "doc" or node.attr.startswith("_"):
            self.errors.append("Only direct doc.field access is permitted")
        self.generic_visit(node)
    def visit_Name(self, node):
        if node.id.startswith("_"):
            self.errors.append("Private and dunder names are not permitted")
        self.generic_visit(node)
    def visit_Call(self, node):
        if not isinstance(node.func, ast.Name) or node.func.id not in ({"throw", "msgprint"} | set(_SCRIPT_BUILTINS)):
            self.errors.append("Only throw(), msgprint() and approved scalar helpers may be called")
        if any(k.arg is None for k in node.keywords):
            self.errors.append("Argument expansion is not permitted")
        self.generic_visit(node)
    def visit_Assign(self, node):
        for target in node.targets:
            if not isinstance(target, ast.Name) and not (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "doc"):
                self.errors.append("Assignments are limited to local variables and doc.field")
        self.generic_visit(node)
    def visit_AugAssign(self, node):
        if not isinstance(node.target, ast.Name) and not (isinstance(node.target, ast.Attribute) and isinstance(node.target.value, ast.Name) and node.target.value.id == "doc"):
            self.errors.append("Augmented assignments are limited to local variables and doc.field")
        self.generic_visit(node)


def _compile_server_script(source, name="Server Script"):
    if not isinstance(source, str) or len(source) > MAX_CODE:
        raise ValidationError("Server Script source exceeds the 100 KB limit")
    try:
        tree = ast.parse(source, filename=f"<{name}>", mode="exec")
    except SyntaxError as exc:
        raise ValidationError(f"Server Script syntax error: {exc}") from None
    if len(list(ast.walk(tree))) > 1500:
        raise ValidationError("Server Script is too complex")
    validator = _ServerScriptValidator(); validator.visit(tree)
    if validator.errors:
        raise ValidationError("Unsafe Server Script: " + "; ".join(dict.fromkeys(validator.errors))[:1000])
    tree = ast.fix_missing_locations(_SizeGuard().visit(tree))
    return compile(tree, filename=f"<{name}>", mode="exec")


_COMPILED: dict = {}
def _cached_code(row):
    """Compiling (parse + validate + rewrite) once per saved version, not on every document event."""
    key = (row.get('id'), row.get('version'), row['code'])
    code = _COMPILED.get(key)
    if code is None:
        code = _compile_server_script(row['code'], row.get('name', 'Server Script'))
        if len(_COMPILED) >= 256: _COMPILED.clear()
        _COMPILED[key] = code
    return code


def _run_server_script(row, doc):
    proxy = _DocProxy(doc)
    def throw(message): raise ValidationError(str(message))
    def msgprint(message): return str(message)
    code = _cached_code(row)
    glb = {"__builtins__": _SCRIPT_BUILTINS, "doc": proxy, "throw": throw, "msgprint": msgprint, "_vl_add": _vl_add, "_vl_mul": _vl_mul, "_vl_mod": _vl_mod}
    try:
        exec(code, glb, glb)
    except ValidationError:
        raise
    except Exception as exc:                          # 1/0, a missing field, a wrong type ...: tell the user which script failed, never a bare HTTP 500
        raise ValidationError(f"Server Script {row.get('name', 'Server Script')!r} failed: {type(exc).__name__}: {exc}") from None

def run_server_scripts(doc,event):
    # The registry is provisioned at site load. During tests or a manual schema reset,
    # absence means there are simply no custom scripts yet; never run DDL in this hook.
    with db.transaction() as c:
        if c.engine not in _table_known:
            if not inspect(c).has_table('vl_custom_script'):
                return
            _table_known.add(c.engine)                  # (schema reflection on EVERY insert/save/submit was a measurable cost)
        from .permissions import _remember                # inside a bulk import the scripts cannot change: read each (DocType, event) once
        rows=_remember(("server_scripts",doc.doctype,event),lambda: [dict(r) for r in c.execute(select(scripts).where(scripts.c.script_type=='server',scripts.c.doctype==doc.doctype,
            scripts.c.event==event,scripts.c.enabled==1).order_by(scripts.c.name)).mappings().all()])
    for row in rows: _run_server_script(row,doc)

def install_routes(app, scope, run):
    @app.get('/api/custom-scripts')
    def scripts_list(request:Request, script_type:str|None=None, doctype:str|None=None):
        return run(request,lambda:list_scripts(script_type,doctype))
    @app.post('/api/custom-scripts')
    def scripts_save(request:Request, body:dict=Body(...)):
        return run(request,lambda:save_script(body))
    @app.post('/api/custom-scripts/validate')
    def scripts_validate(request:Request, body:dict=Body(...)):
        return run(request,lambda:validate_script(body))
    @app.get('/api/custom-scripts/{script_id}/versions')
    def scripts_versions(script_id:str,request:Request):
        return run(request,lambda:script_history(script_id))
    @app.post('/api/custom-scripts/{script_id}/restore/{version}')
    def scripts_restore(script_id:str,version:int,request:Request):
        return run(request,lambda:restore_script(script_id,version))
    @app.delete('/api/custom-scripts/{script_id}')
    def scripts_delete(script_id:str,request:Request):
        return run(request,lambda:delete_script(script_id))
