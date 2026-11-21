type Datum={value?:string|number|null;count?:number;label?:string;amount?:number;[key:string]:unknown};
const PALETTE=["var(--brand,#3867d6)","#0f9d78","#d97706","#8b5cf6","#db547b","#0891b2"];
export default function DashboardChart({data,kind="bar"}:{data:Datum[];kind?:string}){
 const keys=Array.from(new Set(data.flatMap(d=>Object.keys(d).filter(k=>!["value","count","label"].includes(k)&&typeof d[k]==="number"))));
 const series=keys.length?keys:["count"];
 const rows=data.slice(0,30).map(d=>({label:String(d.label??d.value??"(blank)"),values:series.map(k=>Number(d[k]??(k==="count"?d.count:d.amount)??0))}));
 const max=Math.max(1,...rows.flatMap(r=>r.values));
 if(kind==="line"){
  const lines=series.map((key,j)=>({key,color:PALETTE[j%PALETTE.length],points:rows.map((r,i)=>`${rows.length<2?50:i*100/(rows.length-1)},${92-r.values[j]/max*82}`).join(" ")}));
  return <div className="dashboard-chart-wrap"><svg className="dash-chart" viewBox="0 0 100 100" role="img" aria-label="Line chart">{lines.map((l,j)=><g key={l.key}><polyline points={l.points} fill="none" stroke={l.color} strokeWidth="2" vectorEffect="non-scaling-stroke"/>{rows.map((r,i)=><circle key={i} cx={rows.length<2?50:i*100/(rows.length-1)} cy={92-r.values[j]/max*82} r="2" fill={l.color}/>)}</g>)}</svg><div className="chart-legend">{lines.map(l=><span key={l.key}><i style={{background:l.color}}/>{l.key}</span>)}</div></div>;
 }
 if(kind==="pie"||kind==="doughnut"){
  const values=rows.map(r=>r.values.reduce((a,b)=>a+b,0));const total=values.reduce((a,b)=>a+b,0)||1;let cursor=0;
  const paths=rows.map((r,i)=>{const start=cursor/total*Math.PI*2;cursor+=values[i];const end=cursor/total*Math.PI*2;const large=end-start>Math.PI?1:0;const x1=50+42*Math.sin(start),y1=50-42*Math.cos(start),x2=50+42*Math.sin(end),y2=50-42*Math.cos(end);return <path key={i} d={`M50 50 L${x1} ${y1} A42 42 0 ${large} 1 ${x2} ${y2} Z`} fill={PALETTE[i%PALETTE.length]}/>;});
  return <div className="dashboard-chart-wrap"><svg className="dash-chart" viewBox="0 0 100 100" role="img" aria-label={kind+" chart"}>{paths}{kind==="doughnut"&&<circle cx="50" cy="50" r="23" fill="var(--card)"/>}</svg><div className="chart-legend">{rows.map((r,i)=><span key={r.label}><i style={{background:PALETTE[i%PALETTE.length]}}/>{r.label}</span>)}</div></div>;
 }
 return <div className="chart-bars">{rows.map((r,i)=><div key={i} className="chart-row"><span title={r.label}>{r.label}</span><div className="chart-series-bars">{r.values.map((v,j)=><i key={j} title={`${series[j]}: ${v}`} style={{width:`${v/max*100}%`,background:PALETTE[j%PALETTE.length]}}/>)}</div><b>{r.values.reduce((a,b)=>a+b,0).toLocaleString()}</b></div>)}</div>;
}
