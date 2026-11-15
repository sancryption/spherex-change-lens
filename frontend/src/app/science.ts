import { useEffect, useState } from "react";
import type { EvidenceResponse, MoversResponse } from "../contracts";
import { readJson } from "./timeline";

async function loadScience<T>(id: string, resource: string, signal?: AbortSignal): Promise<T> {
  const result = await readJson<T & { investigation_id: string }>(
    await fetch(`/api/v1/investigations/${encodeURIComponent(id)}/${resource}`, { signal }),
  );
  if (!result || result.investigation_id !== id) throw new Error("Science response does not match this investigation.");
  return result;
}
export const loadMovers = (id: string, signal?: AbortSignal) => loadScience<MoversResponse>(id, "movers", signal);
export const loadEvidence = (id: string, signal?: AbortSignal) => loadScience<EvidenceResponse>(id, "evidence", signal);

export function useScience<T>(id: string, loader: (id: string, signal?: AbortSignal) => Promise<T>) {
  const [result, setResult] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError("");
    setResult(null);
    loader(id, controller.signal).then(
      value => { if (active) setResult(value); },
      reason => { if (active) setError(reason instanceof Error ? reason.message : "Science request failed."); },
    ).finally(() => { if (active) setLoading(false); });
    return () => { active = false; controller.abort(); };
  }, [id, loader, attempt]);
  return { result, error, loading, retry: () => setAttempt(value => value + 1) };
}
