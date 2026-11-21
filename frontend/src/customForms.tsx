import type { ComponentType } from "react";
import type { Doc, Meta } from "./types";
import type { FormApi } from "./clientScripts";

/** Installed frontend apps register React forms at application startup. Components are bundled app code, not database-evaluated JSX. */
export interface CustomFormProps { doc: Doc; meta: Meta; frm: FormApi; readOnly: boolean; isNew: boolean; onChange(fieldname: string, value: unknown): void; }
type FormRegistration = { component: ComponentType<CustomFormProps>; owner: string };
const forms = new Map<string, FormRegistration>();
export function registerFormComponent(doctype: string, component: ComponentType<CustomFormProps>, owner = "core") {
  if (!doctype.trim()) throw new Error("A DocType is required to register a custom form");
  forms.set(doctype, { component, owner });
}
export function getFormComponent(doctype: string) { return forms.get(doctype)?.component ?? null; }
export function unregisterFormComponent(doctype: string) { forms.delete(doctype); }
export function unregisterAppComponents(owner: string) {
  for (const [doctype, registration] of forms) if (registration.owner === owner) forms.delete(doctype);
}

/** Public bridge used by self-contained app frontend bundles. */
declare global {
  interface Window {
    Velora?: {
      registerFormComponent: typeof registerFormComponent;
      unregisterFormComponent: typeof unregisterFormComponent;
      unregisterAppComponents: typeof unregisterAppComponents;
    };
  }
}
if (typeof window !== "undefined") {
  window.Velora = {
    ...(window.Velora ?? {}),
    registerFormComponent,
    unregisterFormComponent,
    unregisterAppComponents,
  };
}
