import type { QueryParameters, ObservationFrame, ObservationTimeline } from "./domain";
import { sortEpochsChronologically } from "./domain";

export interface ApiErrorBody {
  error?: { code?: string; message?: string; retryable?: boolean };
  request_id?: string;
}

export class ApiError extends Error {
  readonly code?: string;
  readonly requestId?: string;

  constructor(message: string, code?: string, requestId?: string) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.requestId = requestId;
  }
}

interface InvestigationMetadata {
  investigation_id: string;
}

interface ApiTimelinePayload {
  investigation_id: string;
  epochs: ObservationFrame[];
  total_epochs: number;
}

export async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let body: ApiErrorBody | undefined;
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      // Some proxies return a plain-text error; preserve the status in that case.
    }
    throw new ApiError(
      body?.error?.message ?? `The service returned an error (${response.status}).`,
      body?.error?.code,
      body?.request_id,
    );
  }
  return (await response.json()) as T;
}

/** Uses the documented query -> timeline flow; response shape follows Felix's open API-contract PR. */
export async function loadApiTimeline(
  query: QueryParameters,
  fetcher: typeof fetch = fetch,
): Promise<ObservationTimeline> {
  const investigation = await readJson<InvestigationMetadata>(
    await fetcher("/api/v1/investigations/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(query),
    }),
  );
  const timeline = await readJson<ApiTimelinePayload>(
    await fetcher(
      `/api/v1/investigations/${encodeURIComponent(investigation.investigation_id)}/timeline`,
    ),
  );
  return {
    ...timeline,
    epochs: sortEpochsChronologically(timeline.epochs ?? []),
  };
}

const syntheticDates = [
  "2024-01-12T03:14:00Z",
  "2024-03-09T03:21:00Z",
  "2024-06-16T03:09:00Z",
  "2024-09-22T03:32:00Z",
  "2025-01-18T03:18:00Z",
];

function syntheticPreview(index: number, query: QueryParameters): string {
  // Deterministic generated SVG fixture: no archive imagery or external assets.
  const seed = Math.round(query.ra * 1000 + query.dec * 100) + index * 97;
  const stars = Array.from({ length: 54 }, (_, starIndex) => {
    const x = (seed * (starIndex + 17) * 37) % 700 + 10;
    const y = (seed * (starIndex + 23) * 53) % 460 + 10;
    const radius = starIndex % 13 === 0 ? 1.8 : 0.8;
    const opacity = 0.35 + ((starIndex * 17) % 60) / 100;
    return `<circle cx="${x}" cy="${y}" r="${radius}" fill="#dce9ff" opacity="${opacity}"/>`;
  }).join("");
  const drift = index * 5;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 480"><defs><radialGradient id="g"><stop stop-color="#152845"/><stop offset="1" stop-color="#060a12"/></radialGradient></defs><rect width="720" height="480" fill="url(#g)"/>${stars}<circle cx="360" cy="240" r="5" fill="#f6d58d"/><circle cx="${360 + drift}" cy="240" r="18" fill="none" stroke="#7cc8ff" stroke-opacity=".7"/><path d="M 327 240 H 393 M 360 207 V 273" stroke="#7cc8ff" stroke-opacity=".45"/><rect x="18" y="18" width="170" height="28" rx="5" fill="#a84c2d" fill-opacity=".94"/><text x="31" y="37" fill="white" font-family="Arial,sans-serif" font-size="14" font-weight="700" letter-spacing="1">SYNTHETIC DATA</text><text x="18" y="458" fill="#aab8cb" font-family="monospace" font-size="12">GENERATED DEMO FRAME ${String(index + 1).padStart(2, "0")}</text></svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

export async function loadSyntheticTimeline(
  query: QueryParameters,
): Promise<ObservationTimeline> {
  const epochs: ObservationFrame[] = syntheticDates.map((timestamp, index) => ({
    epoch_id: `synthetic-${index + 1}`,
    observation_time_utc: timestamp,
    mjd: Date.parse(timestamp) / 86_400_000 + 40_587,
    band_id: `SPHEREx demo band ${String(index + 1).padStart(2, "0")}`,
    preview_url: syntheticPreview(index, query),
    flags_summary: {},
    quality_warning: false,
    data_origin: "synthetic",
    warnings: ["Generated interface fixture; not an astronomical observation."],
  }));
  return {
    investigation_id: "synthetic-local-demo",
    total_epochs: epochs.length,
    epochs: sortEpochsChronologically(epochs),
  };
}
