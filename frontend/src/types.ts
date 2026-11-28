export type FieldType =
  | "Data" | "Text" | "Int" | "Float" | "Currency" | "Check" | "Date" | "Datetime"
  | "Select" | "Link" | "Dynamic Link" | "Small Text" | "Long Text" | "Code" | "Percent" | "Email" | "Phone" | "JSON" | "Table" | "Section Break" | "Column Break" | "Tab Break";

export interface FieldAppearance {
  label_position?: "top" | "left";
  control_size?: "small" | "medium" | "large";
  display_style?: "standard" | "compact" | "emphasized";
  placeholder?: string;
  help_text?: string;
  show_description?: boolean;
  readonly_style?: boolean;
}

export interface Field {
  fieldname: string;
  fieldtype: FieldType;
  label: string;
  options?: string | string[]; // Select: string[]; Link/Table: target DocType
  required?: boolean;
  unique?: boolean;
  default?: unknown;
  read_only?: boolean;
  hidden?: boolean;
  in_list_view?: boolean;
  in_standard_filter?: boolean;
  length?: number;
  description?: string;
  depends_on?: string;
  mandatory_depends_on?: string;
  read_only_depends_on?: string;
  fetch_from?: string;   // "<link field>.<field>": copied from the linked document when the link is set
  link_filters?: [string, string, unknown][];   // Link only: the picker offers (and the server accepts) only records that meet these
}

export interface Cell { field: string; span: number }
export interface GridSection { label: string; collapsible?: boolean; auto?: boolean; rows: Cell[][] }
export interface GridTab { label: string; sections: GridSection[] }
export interface GridLayout { tabs: GridTab[] }
export interface GridColumn { field: string; width: number }

export interface Meta {
  name: string;
  module: string;
  autoname: string | null;
  title_field: string | null;
  image_field?: string | null;
  is_submittable: boolean;
  istable: boolean;
  track_changes: boolean;
  sort_field: string;
  sort_order: "asc" | "desc";
  fields: Field[];
  layout?: GridLayout; layout_source?: "app" | "company"; grid_columns?: GridColumn[]; can_customize?: boolean;
  form_appearance?: Record<string, FieldAppearance>;
  permissions: Partial<Record<"read" | "write" | "create" | "delete" | "submit" | "cancel" | "export" | "share" | "email" | "print", boolean>>;
}

export interface DocTypeInfo {
  name: string;
  module: string;
  app: string;
  is_submittable: boolean;
  can_create: boolean;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Doc = Record<string, any>;
