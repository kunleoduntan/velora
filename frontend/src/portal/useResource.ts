import { useCallback, useEffect, useRef, useState } from "react";

export interface Resource<T> { data: T | null; error: string; loading: boolean; reload: () => void }

/** Load something once per `deps` change, ignore answers that arrive after the page has moved on, and let the caller retry. */
export function useResource<T>(load: () => Promise<T>, deps: unknown[]): Resource<T> {
  const [state, setState] = useState<{ data: T | null; error: string; loading: boolean }>({ data: null, error: "", loading: true });
  const [tick, setTick] = useState(0);
  const latest = useRef(0);
  const loader = useRef(load);
  loader.current = load;
  useEffect(() => {
    const mine = ++latest.current;
    setState(s => ({ ...s, loading: true, error: "" }));
    loader.current().then(
      data => { if (mine === latest.current) setState({ data, error: "", loading: false }); },
      e => { if (mine === latest.current) setState({ data: null, error: e instanceof Error ? e.message : "Something went wrong.", loading: false }); });
    return () => { latest.current++; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  const reload = useCallback(() => setTick(t => t + 1), []);
  return { ...state, reload };
}
