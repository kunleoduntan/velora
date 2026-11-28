import type { ComponentType, ReactNode } from "react";
export type WebsiteBlock = {type?:string;title?:string;text?:string;image?:string;href?:string;label?:string;items?:Array<{label:string;href:string}>;[key:string]:unknown};
type WebsiteBlockRenderer=ComponentType<{block:WebsiteBlock}>;
const renderers=new Map<string,WebsiteBlockRenderer>();
/** Installed apps can register blocks; commerce behaviour remains in the app, not framework core. */
export function registerWebsiteBlock(type:string,renderer:WebsiteBlockRenderer){if(!/^[a-z][a-z0-9_]{1,63}$/.test(type))throw new Error("Website block type must be a lowercase identifier");renderers.set(type,renderer);}
export function renderWebsiteBlock(block:WebsiteBlock,key:string):ReactNode{
 const Renderer=renderers.get(String(block.type||""));if(Renderer)return <Renderer key={key} block={block}/>;
 if(block.type==="image")return <section className="public-block" key={key}>{block.title&&<h2>{block.title}</h2>}{block.image&&<img src={block.image} alt={block.title||""}/>}</section>;
 if(block.type==="link"||block.type==="button")return <section className="public-block" key={key}><a className="public-cta" href={String(block.href||"#")}>{String(block.label||block.title||"Learn more")}</a></section>;
 if(block.type==="navigation")return <nav className="public-nav" key={key}>{(block.items||[]).map((item,i)=><a key={i} href={item.href}>{item.label}</a>)}</nav>;
 if(block.type==="hero")return <section className="public-hero" key={key}>{block.image&&<img src={block.image} alt=""/>}<div><h2>{block.title}</h2><p>{block.text}</p>{block.href&&<a className="public-cta" href={block.href}>{String(block.label||"Learn more")}</a>}</div></section>;
 return <section className="public-block" key={key}>{block.title&&<h2>{block.title}</h2>}{block.text&&<p>{block.text}</p>}</section>;
}
