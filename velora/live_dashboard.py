"""Token-protected live operations dashboard; bind to loopback by default."""
from __future__ import annotations
import hmac, os
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from .ops_console import operations_snapshot
from .workspace import Workspace

PAGE = """<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Velora Live Operations</title><style>body{font:15px system-ui;background:#f3f6fa;color:#172033;margin:0}header{background:#14213d;color:white;padding:22px 5vw}main{max-width:1100px;margin:25px auto;padding:0 18px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}.card{background:white;border:1px solid #dce3ed;border-radius:12px;padding:18px}.card small{color:#65718a}.card strong{display:block;font-size:24px;margin-top:8px}button{padding:9px 14px;border:0;border-radius:8px;background:#315b9a;color:white;cursor:pointer}</style></head><body><header><h1>Velora Live Operations</h1><p id='stamp'>Connecting…</p><button onclick='refresh()'>Refresh now</button></header><main><div id='cards' class='grid'></div><pre id='error'></pre></main><script>let token=sessionStorage.getItem('velora_ops_token');if(!token){token=prompt('Operations access token');if(token)sessionStorage.setItem('velora_ops_token',token)}async function refresh(){try{const r=await fetch('/api/ops',{headers:{Authorization:'Bearer '+token}});if(!r.ok)throw Error('Access denied or monitoring unavailable ('+r.status+')');const d=await r.json();const h=d.health||{},db=d.databases||{},rec=d.recovery||{},st=h.storage||{};const vals=[['Overall',d.overall],['Sites',(h.sites||{}).count??0],['Applications',((h.applications||{}).registered||[]).length],['Healthy databases',(db.healthy??0)+' / '+(db.checked??0)],['Free storage',(st.free_percent??0)+'%'],['Recovery',rec.status||'unknown'],['Estimated RPO',rec.estimated_rpo_hours==null?'Unknown':rec.estimated_rpo_hours+' hours'],['Log errors',(h.logs||{}).recent_error_lines??0]];document.getElementById('cards').innerHTML=vals.map(x=>'<article class="card"><small>'+String(x[0]).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))+'</small><strong>'+String(x[1]).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))+'</strong></article>').join('');document.getElementById('stamp').textContent='Updated '+d.generated_at;document.getElementById('error').textContent=''}catch(e){document.getElementById('error').textContent=e.message}}refresh();setInterval(refresh,15000)</script></body></html>"""

def create_dashboard_app(ws: Workspace, token: str | None = None) -> FastAPI:
    secret=token or os.environ.get("VELORA_OPS_DASHBOARD_TOKEN")
    if not secret or len(secret) < 24:
        raise RuntimeError("Set VELORA_OPS_DASHBOARD_TOKEN to a random value of at least 24 characters")
    app=FastAPI(title="Velora Operations", docs_url=None, redoc_url=None)
    def authorize(value: str | None):
        supplied=(value or "")
        if not supplied.startswith("Bearer ") or not hmac.compare_digest(supplied[7:], secret):
            raise HTTPException(status_code=401, detail="Unauthorized")
    @app.get("/", response_class=HTMLResponse)
    def index(authorization: str | None = Header(default=None)):
        authorize(authorization); return HTMLResponse(PAGE, headers={"Cache-Control":"no-store"})
    @app.get("/api/ops")
    def status(authorization: str | None = Header(default=None)):
        authorize(authorization); return operations_snapshot(ws)
    return app
