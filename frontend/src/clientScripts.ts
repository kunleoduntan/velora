/** Client-script runtime: `velora.ui.form.on("Customer", { refresh(frm){...}, fieldname(frm){...} })`.
 *  Scripts are trusted app code (shipped with the installed app, served by the backend), run with
 *  access to the `velora` object only. Arbitrary database-stored scripts are NOT supported. */
import { api, apiCall } from "./api";
import { navigate } from "./router";
import type { Doc, Meta } from "./types";

export interface FormApi {
  doc: Doc;
  meta: Meta;
  is_new(): boolean;
  set_value(fieldname: string, value: unknown): void;
  set_table_value(table: string, rowIndex: number, fieldname: string, value: unknown): void;
  add_table_row(table: string, row?: Record<string, unknown>): void;
  get_row_prices(args: Record<string, unknown>): Promise<Record<string, unknown>[]>;
  add_button(label: string, fn: () => void): void;
  set_intro(message: string): void;
  set_read_only(fieldname: string, readOnly?: boolean): void;
  toggle_hidden(fieldname: string, hidden?: boolean): void;
}
export type FormHandler = (frm: FormApi, row?: Record<string, unknown>, rowIndex?: number) => void;
export interface ListSettings {
  add_fields?: string[];
  get_indicator?: (doc: Doc) => [string, string] | null | undefined;
}

const handlers: Record<string, Record<string, FormHandler[]>> = {};

export const velora = {
  ui: {
    form: {
      on(doctype: string, events: Record<string, FormHandler>) {
        const dt = (handlers[doctype] ??= {});
        for (const [ev, fn] of Object.entries(events)) (dt[ev] ??= []).push(fn);
      },
    },
  },
  listview_settings: {} as Record<string, ListSettings>,
  msgprint(message: string, indicator: "info" | "red" | "green" = "info") {
    window.dispatchEvent(new CustomEvent("velora:msg", { detail: { message, indicator } }));
  },
  navigate: (doctype: string, name?: string | null, query?: Record<string, string>) => navigate(doctype, name, query),
  /** Call one of this application's /api/ routes: `await velora.api("POST", "/api/investments/INV-1/accrue", {})`. */
  api: <T = unknown>(method: string, path: string, body?: unknown) => apiCall<T>(method, path, body),
  /** Open a new, unsaved form with some fields already filled in. */
  new_doc(doctype: string, values: Record<string, unknown> = {}) {
    try {
      sessionStorage.setItem("velora.prefill", JSON.stringify({ doctype, mode: "duplicate", source: "", values, amended_from: null, suggested_name: null }));
    } catch { /* storage blocked: the form simply opens empty */ }
    navigate(doctype, "new");
  },
  /** Reload the current form from the server. */
  reload: () => window.dispatchEvent(new Event("velora:reload")),
};

/** Run every handler registered for (doctype, event). `rethrow` lets `validate` abort a save. */
export function trigger(doctype: string, event: string, frm: FormApi, rethrow = false, row?: Record<string, unknown>, rowIndex?: number) {
  for (const fn of handlers[doctype]?.[event] ?? []) {
    try {
      fn(frm, row, rowIndex);
    } catch (e) {
      if (rethrow) throw e;
      console.error(`[velora] ${doctype}.${event} handler failed`, e);
    }
  }
}

const loaded = new Map<string, Promise<void>>();

export function loadScripts(doctype: string, kind: "form" | "list"): Promise<void> {
  const key = `${kind}:${doctype}`;
  if (!loaded.has(key)) {
    loaded.set(key, (async () => {
      const code = await api.clientScript(doctype, kind).catch(() => "");
      if (!code) return;
      try {
        new Function("velora", code)(velora);
      } catch (e) {
        console.error(`[velora] client script for ${doctype} failed`, e);
      }
    })());
  }
  return loaded.get(key)!;
}

/** Test helper. */
export function resetScripts() {
  for (const k of Object.keys(handlers)) delete handlers[k];
  for (const k of Object.keys(velora.listview_settings)) delete velora.listview_settings[k];
  loaded.clear();
}
