import { useEffect, useState } from "react";
import { formatCell } from "../format";

interface Props {
  kind: "Int" | "Float" | "Currency";
  value: unknown;
  onChange: (value: number | null) => void;
  readOnly?: boolean;
  id?: string;
  className?: string;
  placeholder?: string;
}

/** A number box that shows money as money (1,250,000.00) and edits as a plain number: format when you leave it, raw when you type. */
export default function NumberInput({ kind, value, onChange, readOnly, id, className, placeholder }: Props) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const raw = value === null || value === undefined ? "" : String(value);
  useEffect(() => { if (!editing) setText(raw); }, [raw, editing]);
  const shown = editing ? text : formatCell(value, kind);
  return (
    <input
      id={id} className={`${className ?? ""} num-input`.trim()} type="text" inputMode={kind === "Int" ? "numeric" : "decimal"}
      autoComplete="off" readOnly={readOnly} placeholder={placeholder} value={shown}
      onFocus={(e) => { setEditing(true); setText(raw); window.setTimeout(() => e.target.select(), 0); }}
      onChange={(e) => {
        const next = e.target.value.replace(/,/g, "");
        if (next !== "" && !/^-?\d*\.?\d*$/.test(next)) return;
        setText(next);
        const parsed = next === "" || next === "-" || next === "." ? null : Number(next);
        onChange(parsed !== null && Number.isFinite(parsed) ? parsed : null);
      }}
      onBlur={() => setEditing(false)}
    />
  );
}
