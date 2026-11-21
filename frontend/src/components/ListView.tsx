import { useEffect, useMemo, useRef, useState } from "react";
import { api, errorMessage, userKey } from "../api";
import { loadScripts, velora, type ListSettings as ScriptSettings } from "../clientScripts";
import { dataFields, describe, fieldInfo, toApi, type Filter } from "../filters";
import { copyText, formatCell, isNumeric, toTsv } from "../format";
import { PAGE_SIZES, defaultListColumns, loadSettings, saveSettings, type ListSettings, type Sort } from "../listSettings";
import { importHash, navigate } from "../router";
import type { Doc, Meta } from "../types";
import ContextMenu, { type ContextEntry } from "../ui/ContextMenu";
import Icon from "../ui/Icon";
import Menu from "../ui/Menu";
import Popover from "../ui/Popover";
import { BulkEditDialog, BulkResultsDialog } from "./list/BulkDialogs";
import ExportDialog from "./list/ExportDialog";
import FilterPopover from "./list/FilterPopover";
import GroupBySidebar from "./list/GroupBySidebar";
import InsertColumnsDialog from "./list/InsertColumnsDialog";
import SortPopover from "./list/SortPopover";
import StandardFilters from "./list/StandardFilters";

const STATUS = ["Draft", "Submitted", "Cancelled"];
const STATUS_COLOR = ["grey", "green", "red"];
const SELECT_ALL_MAX = 500;
type BulkAction = "delete" | "submit" | "cancel" | "update";
const CHK_W = 40, STATUS_W = 120, MOD_W = 150, MIN_W = 60;

export default function ListView({ doctype, query }: { doctype: string; query: Record<string, string> }) {
  const user = userKey();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [settings, setSettings] = useState<ListSettings>(() => loadSettings(user, doctype));
  const [script, setScript] = useState<ScriptSettings>({});
  const [rows, setRows] = useState<Doc[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [tick, setTick] = useState(0);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [dialog, setDialog] = useState<null | "export" | "edit">(null);
  const [results, setResults] = useState<null | { verb: string; list: { name: string; ok: boolean; error?: string }[] }>(null);
  const [viewName, setViewName] = useState("");
  const [showSidebar, setShowSidebar] = useState(true);
  const [insertDlg, setInsertDlg] = useState<null | { after: string | null }>(null);
  const [menu, setMenu] = useState<null | { x: number; y: number; col: string }>(null);
  const [liveWidths, setLiveWidths] = useState<Record<string, number>>({});
  const [totalsData, setTotalsData] = useState<Record<string, number | null>>({});
  const lastClicked = useRef<number | null>(null);

  const update = (patch: Partial<ListSettings>, resetPage = true) => {
    setSettings((s) => { const n = { ...s, ...patch }; saveSettings(user, doctype, n); return n; });
    if (resetPage) setPage(0);
  };
  const updateView = (fn: (s: ListSettings) => Partial<ListSettings>) =>   // layout-only changes: no refetch, no page reset
    setSettings((s) => { const n = { ...s, ...fn(s) }; saveSettings(user, doctype, n); return n; });

  useEffect(() => { setSettings(loadSettings(user, doctype)); setMeta(null); setSearch(""); setPage(0); setSelected(new Set()); }, [doctype, user]);
  useEffect(() => { setPage(0); setSelected(new Set()); }, [JSON.stringify(query)]);

  // ---- effective filters / columns / sort --------------------------------------------------------
  const urlFilters: Filter[] = useMemo(() => Object.entries(query).map(([field, value]) => ({ field, op: "=", value })), [JSON.stringify(query)]); // eslint-disable-line
  const allFilters = useMemo(() => {
    const f = [...settings.filters, ...urlFilters];
    if (search.trim()) f.push({ field: "_search", op: "like", value: search.trim() });
    return f;
  }, [settings.filters, urlFilters, search, meta]);
  const apiFilters = useMemo(() => toApi(allFilters), [allFilters]);
  const apiKey = JSON.stringify(apiFilters);

  const known = useMemo(() => new Set(meta ? dataFields(meta).map((f) => f.fieldname) : []), [meta]);
  const columns = useMemo(() => {
    if (!meta) return [];
    const base = settings.columns ?? defaultListColumns(meta.fields);
    return base.filter((c) => known.has(c) && c !== "name");
  }, [meta, settings.columns, known]);
  const sortSpec: Sort | null = settings.sort && known.has(settings.sort.field) ? settings.sort : null;
  const orderBy = sortSpec ? `${sortSpec.field} ${sortSpec.order}` : undefined;

  // ---- load data ---------------------------------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const m = await api.meta(doctype);
        await loadScripts(doctype, "list");
        const s = velora.listview_settings[doctype] ?? {};
        const valid = new Set(dataFields(m).map((f) => f.fieldname));
        const base = settings.columns ?? defaultListColumns(m.fields);
        const fields = [...new Set(["name", ...base.filter((c) => valid.has(c)), ...(s.add_fields ?? []).filter((c) => valid.has(c)), "docstatus", "modified"])];
        const ob = settings.sort && valid.has(settings.sort.field) ? `${settings.sort.field} ${settings.sort.order}` : undefined;
        const [data, count] = await Promise.all([
          api.list(doctype, { filters: apiFilters, fields, order_by: ob, limit: settings.pageSize, offset: page * settings.pageSize }),
          api.count(doctype, apiFilters),
        ]);
        if (cancelled) return;
        setMeta(m); setScript(s); setRows(data); setTotal(count); setError("");
      } catch (e) {
        if (!cancelled) setError(errorMessage(e));
      } finally { if (!cancelled) setLoading(false); }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doctype, apiKey, settings.sort, settings.columns, settings.pageSize, page, tick]);

  useEffect(() => {
    if (!meta || !settings.totals) return;
    const numeric = columns.filter((c) => meta.fields.some((f) => f.fieldname === c && isNumeric(f.fieldtype)));
    if (!numeric.length) { setTotalsData({}); return; }
    let cancelled = false;
    api.aggregate(doctype, numeric, apiFilters).then((d) => { if (!cancelled) setTotalsData(d); }).catch(() => { if (!cancelled) setTotalsData({}); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meta, settings.totals, columns.join(","), apiKey, tick, doctype]);

  if (error && !meta) return <div className="panel error" role="alert">{error}</div>;
  if (!meta) return <div className="panel">Loading…</div>;

  const perms = meta.permissions;
  const pageNames = rows.map((r) => r.name as string);
  const from = total === 0 ? 0 : page * settings.pageSize + 1;
  const to = Math.min(total, (page + 1) * settings.pageSize);
  const showStatus = !!script.get_indicator || meta.is_submittable;
  const sel = [...selected];
  const allOnPage = pageNames.length > 0 && pageNames.every((n) => selected.has(n));
  const canSelectAll = allOnPage && total > pageNames.length && total <= SELECT_ALL_MAX && selected.size < total;
  const colInfo = (c: string) => fieldInfo(meta, c);
  const filtersActive = settings.filters.length + urlFilters.length + (search ? 1 : 0);

  // ---- grid layout: fixed widths, sticky (pinned) columns, resizing --------------------------------
  const defaultWidth = (c: string) => { const t = colInfo(c).fieldtype; return c === "name" ? 150 : isNumeric(t) ? 130 : t === "Date" || t === "Datetime" ? 140 : t === "Check" ? 90 : 180; };
  const widthOf = (c: string) => liveWidths[c] ?? settings.widths?.[c] ?? defaultWidth(c);
  const pinnedPrefix: string[] = [];
  for (const c of columns) { if (settings.pinned?.includes(c)) pinnedPrefix.push(c); else break; }   // sticky only works as a left-hand block
  if (!pinnedPrefix.length && settings.freeze !== 0) {                    // nothing pinned by hand: freeze panes after the fifth column (ID + four), as long as they leave room to scroll
    let used = CHK_W + widthOf("name");
    const room = (typeof window !== "undefined" ? window.innerWidth : 1600) * 0.6;
    for (const c of columns.slice(0, Math.max(0, (settings.freeze ?? 5) - 1))) { if (pinnedPrefix.length >= 1 && used + widthOf(c) > room) break; used += widthOf(c); pinnedPrefix.push(c); }
  }
  const stickyCols = ["name", ...pinnedPrefix];
  const leftOf: Record<string, number> = {};
  { let acc = CHK_W; for (const c of stickyCols) { leftOf[c] = acc; acc += widthOf(c); } }
  const allCols = ["name", ...columns];
  const tableWidth = CHK_W + allCols.reduce((a, c) => a + widthOf(c), 0) + (showStatus ? STATUS_W : 0) + MOD_W;
  const stickyProps = (c: string) => (stickyCols.includes(c) ? { className: "sticky-col", style: { left: leftOf[c] } } : { className: "" });

  function startResize(c: string, e: React.MouseEvent) {
    e.preventDefault(); e.stopPropagation();
    const startX = e.clientX, startW = widthOf(c);
    let w = startW;
    const move = (ev: MouseEvent) => { w = Math.max(MIN_W, Math.round(startW + ev.clientX - startX)); setLiveWidths((l) => ({ ...l, [c]: w })); };
    const up = () => {
      document.removeEventListener("mousemove", move); document.removeEventListener("mouseup", up);
      setLiveWidths({});
      updateView((s) => ({ widths: { ...s.widths, [c]: w } }));
    };
    document.addEventListener("mousemove", move); document.addEventListener("mouseup", up);
  }
  const resetWidth = (c: string) => updateView((s) => { const w = { ...s.widths }; delete w[c]; return { widths: w }; });
  function pinColumn(c: string, on: boolean) {
    if (!on) return update({ pinned: settings.pinned.filter((x) => x !== c) }, false);
    const pinned = [...pinnedPrefix, c];
    update({ pinned, columns: [...pinned, ...columns.filter((x) => !pinned.includes(x))] }, false);   // pinned columns move to the left
  }
  function columnMenu(c: string): ContextEntry[] {
    const t = colInfo(c).fieldtype;
    const text = !isNumeric(t) && t !== "Date" && t !== "Datetime";
    return [
      { label: text ? "Sort A to Z" : "Sort smallest to largest", icon: "arrowUp", onClick: () => update({ sort: { field: c, order: "asc" } }) },
      { label: text ? "Sort Z to A" : "Sort largest to smallest", icon: "arrowDown", onClick: () => update({ sort: { field: c, order: "desc" } }) },
      { label: "Clear sort", hidden: sortSpec?.field !== c, onClick: () => update({ sort: null }) },
      { label: "Insert columns…", icon: "columns", onClick: () => setInsertDlg({ after: c }) },
      { label: "Remove this column", icon: "x", hidden: c === "name", onClick: () => update({ columns: columns.filter((x) => x !== c), pinned: settings.pinned.filter((x) => x !== c) }) },
      { label: pinnedPrefix.includes(c) ? "Unpin column" : "Pin column", icon: "bookmark", hidden: c === "name" || !!(!settings.pinned?.length && pinnedPrefix.includes(c)), onClick: () => pinColumn(c, !pinnedPrefix.includes(c)) },
      { label: "Freeze columns up to here", icon: "bookmark", hidden: c === "name", onClick: () => { const upTo = columns.slice(0, columns.indexOf(c) + 1); update({ pinned: upTo, freeze: undefined }, false); } },
      { label: "Unfreeze columns", icon: "x", hidden: !pinnedPrefix.length, onClick: () => update({ pinned: [], freeze: 0 }, false) },
      { label: "Reset width", hidden: !settings.widths?.[c], onClick: () => resetWidth(c) },
    ];
  }

  async function copySelected() {
    const wanted = new Set(sel);
    let data = rows.filter((r) => wanted.has(r.name));
    if (data.length < wanted.size) {
      try {
        const fetched = await api.list(doctype, { filters: [["name", "in", sel]], fields: ["name", ...columns], order_by: orderBy, limit: SELECT_ALL_MAX });
        data = fetched.filter((r) => wanted.has(r.name));
      } catch (e) { setError(errorMessage(e)); return; }
    }
    const text = toTsv(["ID", ...columns.map((c) => colInfo(c).label)], data.map((r) => [r.name, ...columns.map((c) => formatCell(r[c], colInfo(c).fieldtype))]));
    const ok = await copyText(text);
    velora.msgprint(ok ? `Copied ${data.length} row${data.length === 1 ? "" : "s"} to the clipboard` : "Could not copy to the clipboard", ok ? "green" : "red");
  }

  // ---- selection ---------------------------------------------------------------------------------
  function toggleRow(i: number, shift: boolean) {
    const name = pageNames[i];
    setSelected((cur) => {
      const n = new Set(cur);
      if (shift && lastClicked.current !== null) {
        const [a, b] = [Math.min(lastClicked.current, i), Math.max(lastClicked.current, i)];
        const turnOn = !cur.has(name);
        for (let k = a; k <= b; k++) turnOn ? n.add(pageNames[k]) : n.delete(pageNames[k]);
      } else if (n.has(name)) n.delete(name); else n.add(name);
      return n;
    });
    lastClicked.current = i;
  }
  const togglePage = () => setSelected((cur) => { const n = new Set(cur); pageNames.forEach((p) => (allOnPage ? n.delete(p) : n.add(p))); return n; });
  async function selectAllMatching() {
    try {
      const all = await api.list(doctype, { filters: apiFilters, fields: ["name"], order_by: orderBy, limit: SELECT_ALL_MAX });
      setSelected(new Set(all.map((r) => r.name as string)));
    } catch (e) { setError(errorMessage(e)); }
  }

  // ---- bulk actions ------------------------------------------------------------------------------
  const VERB: Record<BulkAction, string> = { delete: "Deleted", submit: "Submitted", cancel: "Cancelled", update: "Updated" };
  async function runBulk(action: BulkAction, values?: Doc) {
    if (!sel.length) return;
    if (action === "delete" && !window.confirm(`Delete ${sel.length} ${doctype} record${sel.length === 1 ? "" : "s"}? This cannot be undone.`)) return;
    setDialog(null);
    try {
      const res = await api.bulk(doctype, { action, names: sel, values });
      const failed = res.filter((r) => !r.ok);
      velora.msgprint(`${VERB[action]} ${res.length - failed.length} of ${res.length}`, failed.length ? "red" : "green");
      if (failed.length) setResults({ verb: VERB[action], list: res });
      setSelected(new Set(failed.map((f) => f.name)));
      setTick((t) => t + 1);
    } catch (e) { setError(errorMessage(e)); }
  }

  // ---- saved views / filters ---------------------------------------------------------------------
  const saveView = () => {
    const name = viewName.trim();
    if (!name) return;
    update({ views: [...settings.views.filter((v) => v.name !== name), { name, filters: settings.filters, columns: settings.columns, sort: settings.sort }] });
    setViewName("");
  };
  const toggleGroup = (field: string, value: string | number | null) => {
    const exists = settings.filters.find((f) => f.field === field && (value === null ? f.op.startsWith("is") : f.op === "=" && String(f.value) === String(value)));
    if (exists) return update({ filters: settings.filters.filter((f) => f !== exists) });
    const rest = settings.filters.filter((f) => !(f.field === field && (f.op === "=" || f.op.startsWith("is"))));
    update({ filters: [...rest, value === null ? { field, op: "is not set", value: "" } : { field, op: "=", value }] });
  };
  const headerSort = (field: string) => {
    if (sortSpec?.field === field) update({ sort: sortSpec.order === "asc" ? { field, order: "desc" } : null });
    else update({ sort: { field, order: "asc" } });
  };

  const stdFields = new Set(meta.fields.filter((f) => f.in_standard_filter).map((f) => f.fieldname));
  const chips = settings.filters.filter((f) => !(stdFields.has(f.field) && (f.op === "=" || f.op === "like") && !Array.isArray(f.value)));

  return (
    <div className="list-page">
      <header className="page-head">
        <div className="titles"><h1>{doctype}</h1><span className="muted" aria-label="Total records">{total.toLocaleString()} record{total === 1 ? "" : "s"}</span></div>
        <div className="search"><Icon name="search" size={14} /><input type="search" placeholder="Search…" aria-label="Search this list" value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(0); }} /></div>
      </header>

      <div className="ribbon" role="toolbar" aria-label="List actions">
        {perms.create && <button type="button" className="rbtn primary" onClick={() => navigate(doctype, "new")}><Icon name="plus" /><span>New</span></button>}
        {perms.create && !meta.istable && <a className="rbtn" href={importHash(doctype)}><Icon name="sheet" /><span>Import</span></a>}
        {perms.delete && <button type="button" className="rbtn danger" disabled={!sel.length} onClick={() => runBulk("delete")}><Icon name="trash" /><span>Delete</span></button>}
        <Menu label="Actions" icon="layers" disabled={!sel.length} items={[
          { label: "Edit…", icon: "edit", hidden: !perms.write, onClick: () => setDialog("edit") },
          { label: "Submit", icon: "submit", hidden: !(meta.is_submittable && perms.submit), onClick: () => runBulk("submit") },
          { label: "Cancel documents", icon: "ban", hidden: !(meta.is_submittable && perms.cancel), onClick: () => runBulk("cancel") },
          { label: "Copy to clipboard", icon: "sheet", onClick: copySelected },
          { label: "Export selected…", icon: "sheet", hidden: !perms.export, onClick: () => setDialog("export") },
        ]} />
        <span className="rsep" />
        <FilterPopover meta={meta} filters={settings.filters} onChange={(f) => update({ filters: f })} />
        <SortPopover meta={meta} sort={sortSpec ?? { field: meta.sort_field, order: meta.sort_order }} onChange={(s) => update({ sort: s })} />
        <button type="button" className="rbtn" onClick={() => setInsertDlg({ after: null })}><Icon name="columns" /><span>Columns</span></button>
        <button type="button" className="rbtn" aria-pressed={settings.totals} onClick={() => updateView((st) => ({ totals: !st.totals }))}><Icon name="sheet" /><span>Totals</span></button>
        <Popover trigger={(p) => <button type="button" className="rbtn" {...p}><Icon name="bookmark" /><span>Views</span>{settings.views.length > 0 && <span className="badge">{settings.views.length}</span>}</button>}>
          {(close) => (
            <div className="views-pop">
              {settings.views.length === 0 && <p className="muted">No saved views yet.</p>}
              <ul>{settings.views.map((v) => (
                <li key={v.name}>
                  <button type="button" className="view-name" onClick={() => { update({ filters: v.filters, columns: v.columns, sort: v.sort }); close(); }}>{v.name}</button>
                  <button type="button" className="icon-btn" aria-label={`Delete view ${v.name}`} onClick={() => update({ views: settings.views.filter((x) => x.name !== v.name) })}><Icon name="x" size={14} /></button>
                </li>))}
              </ul>
              <div className="save-view">
                <input aria-label="View name" placeholder="Save current view as…" value={viewName} onChange={(e) => setViewName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && saveView()} />
                <button type="button" className="rbtn" disabled={!viewName.trim()} onClick={saveView}>Save</button>
              </div>
            </div>
          )}
        </Popover>
        <span className="rsep" />
        <button type="button" className="rbtn" onClick={() => setTick((t) => t + 1)}><Icon name="refresh" /><span>Refresh</span></button>
        {perms.export && <button type="button" className="rbtn" onClick={() => setDialog("export")}><Icon name="sheet" /><span>Export</span></button>}
        <button type="button" className="rbtn" aria-pressed={showSidebar} onClick={() => setShowSidebar((s) => !s)}><Icon name="layers" /><span>{showSidebar ? "Hide" : "Show"} sidebar</span></button>
      </div>

      <StandardFilters meta={meta} filters={settings.filters} onChange={(f) => update({ filters: f })} />

      {(chips.length > 0 || urlFilters.length > 0) && (
        <div className="chips">
          {chips.map((f, i) => (
            <span className="chip" key={i}>{describe(f, meta)}
              <button type="button" aria-label={`Remove filter ${describe(f, meta)}`} onClick={() => update({ filters: settings.filters.filter((x) => x !== f) })}><Icon name="x" size={12} /></button></span>
          ))}
          {urlFilters.map((f) => <span className="chip" key={f.field}>{f.field} = {String(f.value)}</span>)}
          <button className="link" type="button" onClick={() => { update({ filters: [] }); if (urlFilters.length) navigate(doctype); }}>Clear filters</button>
        </div>
      )}

      {error && <div className="error" role="alert">{error}</div>}

      {sel.length > 0 && (
        <div className="selection-bar" role="status">
          <strong>{sel.length} selected</strong>
          {canSelectAll && <button type="button" className="link" onClick={selectAllMatching}>Select all {total.toLocaleString()} records</button>}
          <button type="button" className="link" onClick={() => setSelected(new Set())}>Clear selection</button>
        </div>
      )}

      <div className={`list-body${showSidebar ? "" : " no-side"}`}>
        <div className={`grid-card${loading ? " loading" : ""}`}>
          <div className="grid-scroll">
            <table className="dgrid list-grid fixed" style={{ width: tableWidth, minWidth: "100%" }}>
              <colgroup>
                <col style={{ width: CHK_W }} />
                {allCols.map((c) => <col key={c} style={{ width: widthOf(c) }} />)}
                {showStatus && <col style={{ width: STATUS_W }} />}
                <col style={{ width: MOD_W }} />
              </colgroup>
              <thead>
                <tr>
                  <th className="chk sticky-col" style={{ left: 0 }}><input type="checkbox" aria-label="Select all on this page" checked={allOnPage} onChange={togglePage} /></th>
                  {allCols.map((c) => {
                    const info = colInfo(c);
                    const dir = sortSpec?.field === c ? sortSpec.order : null;
                    const st = stickyProps(c);
                    return (
                      <th key={c} aria-label={info.label} aria-sort={dir ? (dir === "asc" ? "ascending" : "descending") : "none"}
                        className={`${isNumeric(info.fieldtype) ? "num " : ""}${st.className}`} style={st.style}
                        onContextMenu={(e) => { e.preventDefault(); setMenu({ x: e.clientX, y: e.clientY, col: c }); }}>
                        <div className="th-inner">
                          <button type="button" className="th-btn" onClick={() => headerSort(c)}>{info.label}{dir && <Icon name={dir === "asc" ? "arrowUp" : "arrowDown"} size={12} />}</button>
                          <button type="button" className="th-menu" aria-label={`Column options for ${info.label}`}
                            onClick={(e) => { const r = (e.currentTarget as HTMLElement).getBoundingClientRect(); setMenu({ x: r.left, y: r.bottom, col: c }); }}><Icon name="down" size={12} /></button>
                        </div>
                        <span className="resize-handle" role="separator" aria-orientation="vertical" aria-label={`Resize ${info.label}`}
                          onMouseDown={(e) => startResize(c, e)} onDoubleClick={() => resetWidth(c)} />
                      </th>
                    );
                  })}
                  {showStatus && <th>Status</th>}
                  <th>Modified</th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 && (
                  <tr><td colSpan={columns.length + 4} className="empty-row">
                    {filtersActive ? <>No records match your filters. <button type="button" className="link" onClick={() => { update({ filters: [] }); setSearch(""); if (urlFilters.length) navigate(doctype); }}>Clear filters</button></>
                      : <>No records yet.{perms.create && <> <button type="button" className="link" onClick={() => navigate(doctype, "new")}>Create the first {doctype}</button></>}</>}
                  </td></tr>
                )}
                {rows.map((r, i) => {
                  const ind = script.get_indicator?.(r) ?? (meta.is_submittable ? [STATUS[r.docstatus ?? 0], STATUS_COLOR[r.docstatus ?? 0]] : null);
                  const on = selected.has(r.name);
                  return (
                    <tr key={r.name} className={on ? "selected" : ""} tabIndex={0}
                      onClick={(e) => { if (!(e.target as HTMLElement).closest(".chk, a, button")) navigate(doctype, r.name); }}
                      onKeyDown={(e) => e.key === "Enter" && navigate(doctype, r.name)}>
                      <td className="chk sticky-col" style={{ left: 0 }}><input type="checkbox" aria-label={`Select ${r.name}`} checked={on} onChange={() => {}} onClick={(e) => toggleRow(i, e.shiftKey)} /></td>
                      <td {...stickyProps("name")}><a href={`#/app/${encodeURIComponent(doctype)}/${encodeURIComponent(r.name)}`}>{r.name}</a></td>
                      {columns.map((c) => {
                        const t = colInfo(c).fieldtype;
                        const st = stickyProps(c);
                        return <td key={c} className={`${isNumeric(t) ? "num " : ""}${st.className}`} style={st.style}>{t === "Check" ? (r[c] ? <Icon name="check" size={14} /> : "") : formatCell(r[c], t)}</td>;
                      })}
                      {showStatus && <td>{ind ? <span className={`pill pill-${ind[1]}`}>{ind[0]}</span> : ""}</td>}
                      <td className="muted">{String(r.modified ?? "").slice(0, 16).replace("T", " ")}</td>
                    </tr>
                  );
                })}
              </tbody>
              {settings.totals && (
                <tfoot>
                  <tr className="totals" data-testid="totals-row">
                    <td className="chk sticky-col" style={{ left: 0 }} />
                    {allCols.map((c) => {
                      const t = colInfo(c).fieldtype;
                      const st = stickyProps(c);
                      return <td key={c} className={`${isNumeric(t) ? "num " : ""}${st.className}`} style={st.style}>
                        {c === "name" ? `Total (${total.toLocaleString()})` : totalsData[c] != null ? formatCell(totalsData[c], t) : ""}</td>;
                    })}
                    {showStatus && <td />}
                    <td />
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
          <footer className="pager">
            <span>{from}–{to} of {total}</span>
            <label className="page-size">Rows per page
              <select aria-label="Rows per page" value={settings.pageSize} onChange={(e) => update({ pageSize: Number(e.target.value) })}>
                {PAGE_SIZES.map((n) => <option key={n} value={n}>{n}</option>)}
              </select></label>
            <button className="rbtn" type="button" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
            <button className="rbtn" type="button" disabled={to >= total} onClick={() => setPage(page + 1)}>Next</button>
          </footer>
        </div>
        {showSidebar && <GroupBySidebar meta={meta} apiFilters={apiFilters} active={allFilters} onToggle={toggleGroup} tick={tick} />}
      </div>

      {dialog === "export" && <ExportDialog doctype={doctype} columns={columns} apiFilters={apiFilters} orderBy={orderBy} selected={sel} pageNames={pageNames}
        total={total} onClose={() => setDialog(null)} />}
      {insertDlg && <InsertColumnsDialog meta={meta} columns={columns} afterColumn={insertDlg.after}
        onClose={() => setInsertDlg(null)} onApply={(c) => { update({ columns: c, pinned: c ? settings.pinned.filter((p) => c.includes(p)) : [] }); setInsertDlg(null); }} />}
      {menu && <ContextMenu x={menu.x} y={menu.y} items={columnMenu(menu.col)} onClose={() => setMenu(null)} />}
      {dialog === "edit" && <BulkEditDialog meta={meta} count={sel.length} onClose={() => setDialog(null)} onApply={(v) => runBulk("update", v)} />}
      {results && <BulkResultsDialog verb={results.verb} results={results.list} onClose={() => setResults(null)} />}
    </div>
  );
}
