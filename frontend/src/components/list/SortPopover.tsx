import { dataFields } from "../../filters";
import type { Sort } from "../../listSettings";
import type { Meta } from "../../types";
import Icon from "../../ui/Icon";
import Popover from "../../ui/Popover";

export default function SortPopover({ meta, sort, onChange }: { meta: Meta; sort: Sort; onChange: (s: Sort | null) => void }) {
  const fields = dataFields(meta).filter((f) => f.fieldtype !== "JSON" && f.fieldtype !== "Text");
  const label = fields.find((f) => f.fieldname === sort.field)?.label ?? sort.field;
  return (
    <Popover trigger={(p) => (
      <button type="button" className="rbtn" {...p}>
        <Icon name={sort.order === "asc" ? "arrowUp" : "arrowDown"} /><span>Sort: {label}</span>
      </button>
    )}>
      {(close) => (
        <div className="sort-pop">
          <select aria-label="Sort by" value={sort.field} onChange={(e) => onChange({ ...sort, field: e.target.value })}>
            {fields.map((f) => <option key={f.fieldname} value={f.fieldname}>{f.label}</option>)}
          </select>
          <div className="seg" role="group" aria-label="Direction">
            <button type="button" className={sort.order === "asc" ? "on" : ""} onClick={() => onChange({ ...sort, order: "asc" })}>Ascending</button>
            <button type="button" className={sort.order === "desc" ? "on" : ""} onClick={() => onChange({ ...sort, order: "desc" })}>Descending</button>
          </div>
          <div className="popover-actions"><button type="button" className="rbtn" onClick={() => { onChange(null); close(); }}>Reset to default</button></div>
        </div>
      )}
    </Popover>
  );
}
