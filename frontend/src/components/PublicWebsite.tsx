import { useEffect, useState } from "react";
import { renderWebsiteBlock, type WebsiteBlock } from "../website/blocks";

type Page={slug:string;title:string;summary:string;body:string;blocks?:WebsiteBlock[];seo?:Record<string,string>};
export default function PublicWebsite(){
 const slug=decodeURIComponent(window.location.pathname.split("/").filter(Boolean).slice(1).join("/"));
 const [page,setPage]=useState<Page|null>(null),[error,setError]=useState(""),[busy,setBusy]=useState(true);
 useEffect(()=>{fetch(`/api/public/pages/${encodeURIComponent(slug)}`).then(async r=>{const j=await r.json();if(!r.ok)throw new Error(j.message||"Page not found");return j.data as Page;}).then(setPage).catch(e=>setError(e.message)).finally(()=>setBusy(false));},[slug]);
 useEffect(()=>{if(!page)return;document.title=page.seo?.title||page.title;let meta=document.querySelector('meta[name="description"]') as HTMLMetaElement|null;if(!meta){meta=document.createElement("meta");meta.name="description";document.head.appendChild(meta);}meta.content=page.seo?.description||page.summary||"";},[page]);
 if(busy)return <main className="public-site"><p>Loading…</p></main>;
 if(error||!page)return <main className="public-site"><h1>Page unavailable</h1><p>{error||"This page could not be found."}</p></main>;
 return <main className="public-site"><header><a href="/" className="public-brand">Velora</a>{(page.blocks||[]).filter(b=>b.type==="navigation").map((b,i)=>renderWebsiteBlock(b,`nav-${i}`))}</header><article><h1>{page.title}</h1>{page.summary&&<p className="public-summary">{page.summary}</p>}{page.body.split(/\n\s*\n/).filter(Boolean).map((p,i)=><p key={i}>{p}</p>)}{(page.blocks||[]).map((b,i)=>renderWebsiteBlock(b,String(i)))}</article><footer>Powered by Velora</footer></main>;
}
