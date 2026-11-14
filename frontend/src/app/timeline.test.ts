import { describe, expect, it, vi } from "vitest";
import { ApiError, loadApiTimeline, loadSyntheticTimeline } from "./timeline";

describe("timeline adapters", () => {
  it("uses the documented API endpoints and returns frames in chronological order", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ investigation_id: "inv-1" }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        investigation_id: "inv-1",
        total_epochs: 2,
        epochs: [
          { epoch_id: "later", observation_time_utc: "2024-02-01T00:00:00Z", mjd: 60340, band_id: "B2", flags_summary: {}, quality_warning: false, data_origin: "authentic_cached", warnings: [] },
          { epoch_id: "earlier", observation_time_utc: "2024-01-01T00:00:00Z", mjd: 60309, band_id: "B1", flags_summary: {}, quality_warning: false, data_origin: "authentic_cached", warnings: [] },
        ],
      }), { status: 200 }));

    const result = await loadApiTimeline({ ra: 10, dec: -2, radius_arcsec: 60, target_id: "barnards-star" }, fetcher);
    expect(fetcher).toHaveBeenNthCalledWith(1, "/api/v1/investigations/query", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ ra: 10, dec: -2, radius_arcsec: 60, target_id: "barnards-star" }),
    }));
    expect(fetcher).toHaveBeenNthCalledWith(2, "/api/v1/investigations/inv-1/timeline");
    expect(result.epochs.map((epoch) => epoch.epoch_id)).toEqual(["earlier", "later"]);
  });

  it("surfaces safe API error details without failing on a non-JSON proxy response", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({
      error: { code: "ARCHIVE_UNAVAILABLE", message: "Archive is temporarily unavailable.", retryable: true, details: {} },
      request_id: "req-123",
    }), { status: 503 }));
    await expect(loadApiTimeline({ ra: 10, dec: 0, radius_arcsec: 30 }, fetcher)).rejects.toMatchObject({
      name: "ApiError",
      message: "Archive is temporarily unavailable.",
      code: "ARCHIVE_UNAVAILABLE",
      requestId: "req-123",
    });

    const plainTextFetcher = vi.fn().mockResolvedValueOnce(new Response("upstream unavailable", { status: 502 }));
    await expect(loadApiTimeline({ ra: 10, dec: 0, radius_arcsec: 30 }, plainTextFetcher)).rejects.toBeInstanceOf(ApiError);
  });

  it("generates five ordered, clearly marked fixture frames locally", async () => {
    const result = await loadSyntheticTimeline({ ra: 10, dec: 0, radius_arcsec: 30 });
    expect(result.epochs).toHaveLength(5);
    expect(result.epochs.every((epoch) => epoch.data_origin === "synthetic" && epoch.preview_url?.startsWith("data:image/svg+xml"))).toBe(true);
    expect(result.epochs.map((epoch) => epoch.mjd)).toEqual([...result.epochs.map((epoch) => epoch.mjd)].sort((a, b) => a - b));
  });
});
