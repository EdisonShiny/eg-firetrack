// Fetch + cache for /data/*.json (the only data source of the site).
import { useEffect, useState } from "react";

const cache = new Map<string, Promise<unknown>>();

export function loadJSON<T>(path: string): Promise<T> {
  let p = cache.get(path);
  if (!p) {
    p = fetch(`/data/${path}`).then((r) => {
      if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
      return r.json();
    });
    p.catch(() => cache.delete(path));
    cache.set(path, p);
  }
  return p as Promise<T>;
}

export interface Loaded<T> {
  data: T | null;
  error: string | null;
}

/** React hook: data is null while loading (show a skeleton). Pass null to load nothing. */
export function useJSON<T>(path: string | null): Loaded<T> {
  const [state, setState] = useState<Loaded<T> & { path: string | null }>({ data: null, error: null, path: null });
  useEffect(() => {
    if (!path) return;
    let live = true;
    loadJSON<T>(path).then(
      (data) => live && setState({ data, error: null, path }),
      (e: Error) => live && setState({ data: null, error: e.message, path }),
    );
    return () => {
      live = false;
    };
  }, [path]);
  if (state.path !== path) return { data: null, error: null };
  return state;
}
