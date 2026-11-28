import { api } from "./api";
import type { Doc, Field, Meta } from "./types";

/** Fields of `meta` that copy a value from the document picked in link field `linkField` (ERPNext-style "fetch from"). */
export function dependents(meta: Pick<Meta, "fields"> | undefined, linkField: string): { field: Field; target: string }[] {
  return (meta?.fields ?? [])
    .filter((f) => f.fetch_from && f.fetch_from.split(".")[0] === linkField)
    .map((f) => ({ field: f, target: f.fetch_from!.split(".").slice(1).join(".") }));
}

const cache = new Map<string, Promise<Doc | null>>();
const read = (doctype: string, name: string) => {
  const k = `${doctype}\u0000${name}`;
  if (!cache.has(k)) cache.set(k, api.get(doctype, name).catch(() => null));   // no read access / deleted: nothing is fetched, the server still validates the link
  return cache.get(k)!;
};
export const clearFetchCache = () => cache.clear();

/**
 * The values to copy after `linkField` was set to `value`. Fetched fields are replaced when the link changes
 * (clearing the link clears them), exactly like ERPNext, so a stale item name never stays next to a new item.
 */
export async function fetchedValues(meta: Pick<Meta, "fields"> | undefined, linkField: string, value: unknown): Promise<Record<string, unknown>> {
  const deps = dependents(meta, linkField);
  if (!deps.length) return {};
  const link = meta!.fields.find((f) => f.fieldname === linkField);
  const out: Record<string, unknown> = {};
  if (!value || !link?.options) { for (const d of deps) out[d.field.fieldname] = null; return out; }
  const doc = await read(String(link.options), String(value));
  if (!doc) return {};
  for (const d of deps) if (doc[d.target] !== undefined && doc[d.target] !== null) out[d.field.fieldname] = doc[d.target];
  return out;
}
