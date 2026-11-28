import { useEffect, useState } from "react";
import Button from "./Button";
import Dialog from "./Dialog";

/** In-app replacements for the browser's plain confirm / prompt / alert boxes (same look as every other Velora dialog). */
type Req = { kind: "confirm" | "prompt" | "alert"; message: string; initial?: string; resolve: (v: any) => void };
let push: ((r: Req) => void) | null = null;

function open<T>(kind: Req["kind"], message: string, initial?: string, fallback?: () => T): Promise<T> {
  if (!push) return Promise.resolve(fallback ? fallback() : (undefined as T));       // no host mounted (never in the app)
  return new Promise<T>((resolve) => push!({ kind, message, initial, resolve }));
}
export const askConfirm = (message: string) => open<boolean>("confirm", message, undefined, () => window.confirm(message));
export const askPrompt = (message: string, initial = "") => open<string | null>("prompt", message, initial, () => window.prompt(message, initial));
export const askAlert = (message: string) => open<void>("alert", message, undefined, () => window.alert(message));

/** Mount once near the top of the app. */
export function AskHost() {
  const [queue, setQueue] = useState<Req[]>([]);
  const [text, setText] = useState("");
  useEffect(() => { push = (r) => setQueue((q) => [...q, r]); return () => { push = null; }; }, []);
  const cur = queue[0];
  useEffect(() => { if (cur) setText(cur.initial ?? ""); }, [cur]);
  if (!cur) return null;
  const done = (v: unknown) => { cur.resolve(v); setQueue((q) => q.slice(1)); };
  const cancel = () => done(cur.kind === "confirm" ? false : cur.kind === "prompt" ? null : undefined);
  const lines = cur.message.split("\n");
  return (
    <Dialog title={cur.kind === "confirm" ? "Please confirm" : cur.kind === "prompt" ? "Enter a value" : "Notice"} onClose={cancel}
      footer={<>
        {cur.kind !== "alert" && <Button onClick={cancel}>Cancel</Button>}
        <Button variant="primary" autoFocus onClick={() => done(cur.kind === "confirm" ? true : cur.kind === "prompt" ? text : undefined)}>{cur.kind === "alert" ? "OK" : cur.kind === "confirm" ? "Confirm" : "Continue"}</Button>
      </>}>
      {lines.map((l, i) => <p key={i} className="ask-line">{l}</p>)}
      {cur.kind === "prompt" && <input className="ask-input" autoFocus value={text} onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") done(text); }} aria-label={cur.message} />}
    </Dialog>
  );
}
