"""Company-local portal identity, public forms and app-owned data providers."""
from __future__ import annotations
import hashlib, hmac, json, re, secrets, time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from fastapi import Body, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import Boolean, Column, DateTime, JSON, MetaData, String, Table, delete, insert, select, update
from . import db, site as site_mod
from .company import CompanyInfo, company_context
from .controlplane.directory import PlaneDirectory
from .exceptions import DoesNotExistError, PermissionDenied, ValidationError
from .permissions import Session, get_session, session_as

md=MetaData()
users=Table('vl_portal_user',md,Column('id',String(32),primary_key=True),Column('email',String(254),nullable=False,unique=True),Column('full_name',String(180),nullable=False),Column('password_hash',String(256),nullable=False),Column('roles',JSON,nullable=False),Column('status',String(20),nullable=False),Column('created_on',DateTime,nullable=False),Column('last_login',DateTime))
sessions=Table('vl_portal_session',md,Column('id',String(32),primary_key=True),Column('user_id',String(32),nullable=False),Column('token_hash',String(64),nullable=False,unique=True),Column('expires_on',DateTime,nullable=False),Column('created_on',DateTime,nullable=False),Column('last_seen',DateTime))
submissions=Table('vl_portal_submission',md,Column('id',String(32),primary_key=True),Column('form_key',String(100),nullable=False),Column('payload',JSON,nullable=False),Column('status',String(24),nullable=False),Column('submitted_on',DateTime,nullable=False),Column('source_ip_hash',String(64)))
PROVIDERS={}; ACTIONS={}; FORMS={}; PUBLIC_ACTIONS={}; SESSION_HOURS=12

flags=Table('vl_portal_flag',md,Column('user_id',String(32),primary_key=True),Column('must_change',Boolean,nullable=False,default=False),Column('reset_requested_on',DateTime),Column('reset_token_hash',String(64)),Column('reset_expires',DateTime))
def _now(): return datetime.now(timezone.utc).replace(tzinfo=None)
def ensure():
    from .db import extra_tables; extra_tables.ensure(md)
def _email(v):
 v=str(v or '').strip().lower()
 if len(v)>254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',v): raise ValidationError('A valid email address is required')
 return v
def _hash(pw,salt=None):
 if not isinstance(pw,str) or not 10<=len(pw)<=256: raise ValidationError('Portal passwords must contain 10 to 256 characters')
 salt=salt or secrets.token_bytes(16); return 'scrypt$%s$%s'%(salt.hex(),hashlib.scrypt(pw.encode(),salt=salt,n=2**14,r=8,p=1).hex())
def _verify(pw,encoded):
 try:
  alg,salt,digest=encoded.split('$',2); actual=hashlib.scrypt(str(pw).encode(),salt=bytes.fromhex(salt),n=2**14,r=8,p=1).hex()
  return alg=='scrypt' and hmac.compare_digest(actual,digest)
 except (ValueError,TypeError): return False
def create_portal_user(email,full_name,password,roles=None,must_change=False):
 ensure(); email=_email(email); name=str(full_name or '').strip()
 if not name or len(name)>180: raise ValidationError('A full name is required')
 roles=sorted(set(roles or ['Customer Portal']))
 if not roles or any(not isinstance(x,str) or not x.strip() or len(x)>80 for x in roles): raise ValidationError('Invalid portal roles')
 row=dict(id=secrets.token_hex(16),email=email,full_name=name,password_hash=_hash(password),roles=roles,status='active',created_on=_now())
 with db.transaction() as c:
  if c.execute(select(users.c.id).where(users.c.email==email)).first(): raise ValidationError('A portal account already exists for this email')
  c.execute(insert(users).values(**row))
  if must_change: _set_flag(c,row['id'],must_change=True)
 return {k:row[k] for k in ('id','email','full_name','roles','status')}
def set_portal_user_status(email, status):
    """Enable or suspend a portal identity from trusted company-side code."""
    if status not in ("active", "suspended"):
        raise ValidationError("Portal status must be active or suspended")
    ensure()
    with db.transaction() as c:
        result = c.execute(update(users).where(users.c.email == _email(email)).values(status=status))
        if not result.rowcount:
            raise DoesNotExistError("Portal user not found")
        if status != "active":
            user = c.execute(select(users.c.id).where(users.c.email == _email(email))).first()
            c.execute(delete(sessions).where(sessions.c.user_id == user[0]))
    return {"email": _email(email), "status": status}


def _set_flag(c,user_id,**vals):
    if not c.execute(update(flags).where(flags.c.user_id==user_id).values(**vals)).rowcount:
        c.execute(insert(flags).values(user_id=user_id,must_change=vals.get('must_change',False),**{k:v for k,v in vals.items() if k!='must_change'}))
def _strong(password,email=''):
    from .controlplane.passwords import check_strength
    check_strength(str(password or ''),email)
def reset_requests():
    """Emails of portal users who asked for a reset and are waiting for staff (only when no email is set up)."""
    ensure()
    with db.transaction() as c:
        return {r[0] for r in c.execute(select(users.c.email).join(flags,flags.c.user_id==users.c.id).where(flags.c.reset_requested_on.isnot(None)))}
def change_password(user_id, current_password, new_password):
    ensure()
    with db.transaction() as c:
        row = c.execute(select(users).where(users.c.id == user_id)).mappings().first()
        if not row or row["status"] != "active" or not _verify(current_password, row["password_hash"]):
            raise PermissionDenied("Current portal password is incorrect")
        _strong(new_password,row['email'])
        c.execute(update(users).where(users.c.id == user_id).values(password_hash=_hash(new_password)))
        c.execute(delete(sessions).where(sessions.c.user_id == user_id))
        _set_flag(c,user_id,must_change=False,reset_requested_on=None,reset_token_hash=None,reset_expires=None)
    return {"changed": True, "sign_in_again": True}


_FAILS={}; MAX_FAILS=5; LOCK_SECONDS=900
def _throttle_check(email):
 now=time.time(); xs=[t for t in _FAILS.get(email,[]) if now-t<LOCK_SECONDS]; _FAILS[email]=xs
 if len(xs)>=MAX_FAILS: raise PermissionDenied('Too many failed sign-in attempts. Try again in %d minute(s).'%(int((LOCK_SECONDS-(now-xs[0]))//60)+1))
def authenticate(email,password):
 ensure(); email=_email(email); _throttle_check(email); token=None
 with db.transaction() as c:
  u=c.execute(select(users).where(users.c.email==email)).mappings().first()
  if u and u['status']=='active' and _verify(password,u['password_hash']):
   token=secrets.token_urlsafe(40); now=_now()
   c.execute(insert(sessions).values(id=secrets.token_hex(16),user_id=u['id'],token_hash=hashlib.sha256(token.encode()).hexdigest(),expires_on=now+timedelta(hours=SESSION_HOURS),created_on=now))
   c.execute(update(users).where(users.c.id==u['id']).values(last_login=now))
   pending=bool(c.execute(select(flags.c.must_change).where(flags.c.user_id==u['id'])).scalar())
 if token is None:
  _FAILS.setdefault(email,[]).append(time.time()); raise PermissionDenied('Invalid portal email or password')
 _FAILS.pop(email,None)
 return {'token':token,'user':{**_public(u),'must_change':pending}}
def admin_set_password(email,new_password,temporary=False):
 """Trusted company-side code sets a portal password (invitation or reset). All of the person's sessions end."""
 ensure(); email=_email(email); h=_hash(new_password)
 with db.transaction() as c:
  u=c.execute(select(users.c.id).where(users.c.email==email)).first()
  if not u: raise DoesNotExistError('Portal user not found')
  c.execute(update(users).where(users.c.id==u[0]).values(password_hash=h)); c.execute(delete(sessions).where(sessions.c.user_id==u[0]))
  _set_flag(c,u[0],must_change=bool(temporary),reset_requested_on=None,reset_token_hash=None,reset_expires=None)
 _FAILS.pop(email,None); return {'email':email,'password_set':True}
def _public(u): return {'id':u['id'],'email':u['email'],'full_name':u['full_name'],'roles':list(u['roles'] or [])}
def resolve_token(token,allow_pending=False):
 ensure()
 if not token: raise PermissionDenied('Portal sign-in is required')
 digest=hashlib.sha256(token.encode()).hexdigest()
 with db.transaction() as c:
  row=c.execute(select(sessions,users).join(users,users.c.id==sessions.c.user_id).where(sessions.c.token_hash==digest)).mappings().first()
  if not row or row['expires_on']<=_now() or row['status']!='active':
   if row: c.execute(delete(sessions).where(sessions.c.token_hash==digest))
   raise PermissionDenied('Portal session has expired or is invalid')
  c.execute(update(sessions).where(sessions.c.token_hash==digest).values(last_seen=_now()))
  pending=bool(c.execute(select(flags.c.must_change).where(flags.c.user_id==row['user_id'])).scalar())
  if pending and not allow_pending: raise PermissionDenied('You signed in with a temporary password. Choose a new password to continue.')
  return {'id':row['user_id'],'email':row['email'],'full_name':row['full_name'],'roles':list(row['roles'] or []),'must_change':pending}
RESET_MINUTES=30
def request_reset(email,base_url,send=None):
 """Always the same answer. With email set up a one-time link is sent; otherwise the request waits for staff, who issue a temporary password."""
 ensure(); mode='email' if send else 'staff'; answer={'message':'If that email belongs to an active portal account, the next step has been arranged.','mode':mode}
 try: email=_email(email)
 except ValidationError: return answer
 now=_now()
 with db.transaction() as c:
  u=c.execute(select(users).where(users.c.email==email)).mappings().first()
  if not u or u['status']!='active': return answer
  f=c.execute(select(flags).where(flags.c.user_id==u['id'])).mappings().first()
  last=(f.get('reset_requested_on') or ((f.get('reset_expires') or now)-timedelta(minutes=RESET_MINUTES) if f.get('reset_expires') else None)) if f else None
  if last and (now-last).total_seconds()<120: return answer
  token=secrets.token_urlsafe(32) if send else None
  _set_flag(c,u['id'],reset_requested_on=None if send else now,reset_token_hash=hashlib.sha256(token.encode()).hexdigest() if token else None,reset_expires=now+timedelta(minutes=RESET_MINUTES) if token else None,**({} if f else {'must_change':False}))
 if send and token:
  try: send(email,u['full_name'],base_url.rstrip('/')+'/portal#/reset?token='+token,RESET_MINUTES)
  except Exception:
   with db.transaction() as c: _set_flag(c,u['id'],reset_token_hash=None,reset_expires=None)
 return answer
def complete_reset(token,new_password):
 ensure(); digest=hashlib.sha256(str(token or '').encode()).hexdigest(); now=_now()
 with db.transaction() as c:
  u=c.execute(select(users).join(flags,flags.c.user_id==users.c.id).where(flags.c.reset_token_hash==digest,flags.c.reset_expires>now)).mappings().first() if token else None
  if not u or u['status']!='active': raise ValidationError('This reset link is not valid any more. Ask for a new one.')
  _strong(new_password,u['email'])
  c.execute(update(users).where(users.c.id==u['id']).values(password_hash=_hash(new_password))); c.execute(delete(sessions).where(sessions.c.user_id==u['id']))
  _set_flag(c,u['id'],must_change=False,reset_requested_on=None,reset_token_hash=None,reset_expires=None)
 _FAILS.pop(u['email'],None); return {'reset':True}
def logout(token):
 ensure(); digest=hashlib.sha256((token or '').encode()).hexdigest()
 with db.transaction() as c: c.execute(delete(sessions).where(sessions.c.token_hash==digest))
 return {'signed_out':True}
def register_resource_provider(key,provider):
 if not re.fullmatch(r'[a-z][a-z0-9_.-]{1,79}',key) or not callable(provider): raise ValueError('Invalid portal provider')
 if key in PROVIDERS and PROVIDERS[key] is not provider: raise ValueError('Portal provider already registered: '+key)
 PROVIDERS[key]=provider
def register_public_action(key,handler):
 """A page anyone with the link can open (an unsubscribe link, say). handler(params: dict, method: str) -> HTML text. The handler must authenticate the request itself, for example with a signed token."""
 if not callable(handler): raise ValidationError('A public action needs a handler function')
 PUBLIC_ACTIONS[key]=handler
def register_action_provider(key,provider):
 """A signed-in portal user may POST to /api/portal/actions/<key>. ``provider(user, body)`` must derive the person's records from ``user`` only."""
 if not re.fullmatch(r'[a-z][a-z0-9_.-]{1,79}',key) or not callable(provider): raise ValueError('Invalid portal action')
 if key in ACTIONS and ACTIONS[key] is not provider: raise ValueError('Portal action already registered: '+key)
 ACTIONS[key]=provider
def register_public_form(key,fields):
 if not re.fullmatch(r'[a-z][a-z0-9_-]{1,79}',key) or not isinstance(fields,dict) or not fields or len(fields)>40: raise ValueError('Invalid public form')
 clean={}
 for name,spec in fields.items():
  if not re.fullmatch(r'[a-z][a-z0-9_]{0,59}',name) or not isinstance(spec,dict): raise ValueError('Invalid form field')
  typ=spec.get('type','text')
  if typ not in ('text','email','textarea','number','boolean'): raise ValueError('Unsupported field type')
  clean[name]={'type':typ,'required':bool(spec.get('required')),'max_length':min(max(int(spec.get('max_length',500)),1),5000)}
 FORMS[key]=clean
def submit_public_form(key,payload,ip=None):
 ensure(); fields=FORMS.get(key)
 if fields is None: raise DoesNotExistError('Public form not found')
 if not isinstance(payload,dict) or set(payload)-set(fields): raise ValidationError('Unexpected form fields')
 clean={}
 for name,spec in fields.items():
  v=payload.get(name)
  if v in (None,''):
   if spec['required']: raise ValidationError(name+' is required')
   continue
  if spec['type']=='email': clean[name]=_email(v)
  elif spec['type']=='number':
   try: clean[name]=float(v)
   except (ValueError,TypeError): raise ValidationError(name+' must be numeric') from None
  elif spec['type']=='boolean':
   if not isinstance(v,bool): raise ValidationError(name+' must be true or false')
   clean[name]=v
  else:
   if not isinstance(v,str) or len(v)>spec['max_length']: raise ValidationError(name+' exceeds its text limit')
   clean[name]=v.strip()
 rid=secrets.token_hex(16); iphash=hashlib.sha256(ip.encode()).hexdigest() if ip else None
 with db.transaction() as c: c.execute(insert(submissions).values(id=rid,form_key=key,payload=clean,status='new',submitted_on=_now(),source_ip_hash=iphash))
 return {'id':rid,'received':True}
def list_submissions(form_key=None,limit=100):
 s=get_session()
 if s.user!='Administrator' and not {'System Manager','Portal Manager'}.intersection(s.roles): raise PermissionDenied('Portal Manager permission is required')
 ensure(); stmt=select(submissions).order_by(submissions.c.submitted_on.desc()).limit(min(max(limit,1),500))
 if form_key: stmt=stmt.where(submissions.c.form_key==form_key)
 with db.transaction() as c: return [dict(r) for r in c.execute(stmt).mappings()]
@contextmanager
def _company_scope(request,plane):
 if plane is None: yield; return
 co=plane.registry.company_for_domain(request.headers.get('host'))
 if not co or co.get('status')!='active': raise DoesNotExistError('Portal is not configured for this company domain')
 tenant=plane.registry.get_tenant(co['tenant_id']) or {}; site=plane.router.site_for(co)
 info=CompanyInfo(co['id'],co['name'],co['tenant_id'],tenant.get('name',''),PlaneDirectory(plane,co['id']))
 with site_mod.use(site),company_context(info): yield
def install_routes(app:FastAPI,scope,run_request,plane=None):
 def get_token(req):
  auth=req.headers.get('authorization','')
  return auth[7:].strip() if auth.lower().startswith('bearer ') else req.cookies.get('velora_portal_session','')
 def public_run(req,fn):
  with _company_scope(req,plane),db.transaction(): return fn()
 @app.post('/api/portal/auth/login')
 def login(req:Request,body:dict=Body(...)):
  data=public_run(req,lambda:authenticate(body.get('email',''),body.get('password','')))
  resp=JSONResponse({'data':{'user':data['user']}}); resp.set_cookie('velora_portal_session',data['token'],httponly=True,secure=req.url.scheme=='https' or req.headers.get('x-forwarded-proto')=='https',samesite='lax',max_age=SESSION_HOURS*3600,path='/'); return resp
 @app.get('/api/portal/auth/me')
 def me(req:Request): return {'data':{'user':public_run(req,lambda:resolve_token(get_token(req),allow_pending=True))}}
 def _mail_sender():
  try:
   from velora_notify import channels
   cfg=(channels.settings() or {}).get('email') or {}
   if not (cfg.get('host') and cfg.get('from_addr')): return None
   def send(to,name,link,minutes):
    channels.send_email({'recipient':to,'subject':'Reset your portal password','body':'Hello %s,\n\nUse this link to choose a new password. It works once and expires in %d minutes:\n%s\n\nIf you did not ask for this, ignore this email.'%(name,minutes,link),'payload':{'link':link}})
   return send
  except Exception: return None
 @app.post('/api/portal/auth/forgot-password')
 def forgot_portal_password(req:Request,body:dict=Body(...)):
  base=req.headers.get('origin') or str(req.base_url)
  return {'data':public_run(req,lambda:request_reset(str(body.get('email','')),base,_mail_sender()))}
 @app.post('/api/portal/auth/reset-password')
 def reset_portal_password(req:Request,body:dict=Body(...)):
  return {'data':public_run(req,lambda:complete_reset(str(body.get('token','')),str(body.get('new_password',''))))}
 @app.post('/api/portal/auth/change-password')
 def change_portal_password(req:Request,body:dict=Body(...)):
  def change():
   user=resolve_token(get_token(req),allow_pending=True)
   return change_password(user['id'],str(body.get('current_password','')),str(body.get('new_password','')))
  public_run(req,change); resp=JSONResponse({'data':{'changed':True,'sign_in_again':True}}); resp.delete_cookie('velora_portal_session',path='/'); return resp
 @app.post('/api/portal/auth/logout')
 def signout(req:Request):
  public_run(req,lambda:logout(get_token(req))); resp=JSONResponse({'data':{'signed_out':True}}); resp.delete_cookie('velora_portal_session',path='/'); return resp
 @app.get('/api/portal/resources/{key}')
 def resource(key:str,req:Request,params:str='{}'):
  try: args=json.loads(params)
  except ValueError: raise ValidationError('params must be valid JSON') from None
  provider=PROVIDERS.get(key)
  if provider is None: raise DoesNotExistError('Portal resource is not available')
  def fetch():
   user=resolve_token(get_token(req))
   with session_as(Session(user['email'],frozenset(user['roles']))): return {'data':provider(user,args)}
  return public_run(req,fetch)
 @app.post('/api/portal/actions/{key}')
 def action(key:str,req:Request,body:dict=Body(...)):
  handler=ACTIONS.get(key)
  if handler is None: raise DoesNotExistError('Portal action is not available')
  def run_action():
   user=resolve_token(get_token(req))
   with session_as(Session(user['email'],frozenset(user['roles']))): return {'data':handler(user,body)}
  return public_run(req,run_action)
 def _public_action(key:str,req:Request):
  handler=PUBLIC_ACTIONS.get(key)
  if handler is None: raise DoesNotExistError('This page is not available')
  params={k:str(v)[:2000] for k,v in req.query_params.items()}
  html=public_run(req,lambda:handler(params,req.method))
  return HTMLResponse(html,headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})
 app.add_api_route('/api/public/actions/{key}',_public_action,methods=['GET'],operation_id='public_action_get',response_class=HTMLResponse)
 app.add_api_route('/api/public/actions/{key}',_public_action,methods=['POST'],operation_id='public_action_post',response_class=HTMLResponse)
 @app.post('/api/public/forms/{key}')
 def public_form(key:str,req:Request,body:dict=Body(...)):
  return {'data':public_run(req,lambda:submit_public_form(key,body,req.client.host if req.client else None))}
 @app.get('/api/portal/admin/submissions')
 def admin_submissions(req:Request,form_key:str|None=None,limit:int=100): return run_request(req,lambda:list_submissions(form_key,limit))
