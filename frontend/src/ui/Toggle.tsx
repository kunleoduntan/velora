/** Switch control used for Check fields: "No ◯──" / "Yes ──●" */
export default function Toggle({ id, checked, onChange, disabled }: {
  id?: string; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean;
}) {
  return (
    <label className={`toggle${disabled ? " disabled" : ""}`}>
      <span className="toggle-text">{checked ? "Yes" : "No"}</span>
      <input id={id} type="checkbox" role="switch" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span className="track" aria-hidden="true"><span className="thumb" /></span>
    </label>
  );
}
