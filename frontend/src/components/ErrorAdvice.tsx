import type { Advice } from "../api";

/** A refusal that helps: the message, then what to do about it, with buttons that go straight to the fix. */
export default function ErrorAdvice({ error, advice, onField }: { error: string; advice: Advice | null; onField?: (fieldname: string) => void }) {
  if (!error) return null;
  return (
    <div className="error advice" role="alert">
      <div>{error}</div>
      {advice?.hint && <div className="advice-hint"><b>How to fix it:</b> {advice.hint}</div>}
      {(advice?.actions?.length || (advice?.field && onField)) ? (
        <div className="advice-actions">
          {advice?.field && onField && <button type="button" className="rbtn" onClick={() => onField(advice.field!)}>Go to the field</button>}
          {advice?.actions?.map((a) => <a key={a.href + a.label} className="rbtn" href={a.href}>{a.label}</a>)}
        </div>) : null}
    </div>);
}
