import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DifferenceView, PreviewImage, ScienceWorkspace } from "./ScienceWorkspace";
import { loadMovers } from "./science";
import type { DifferenceSummary } from "../contracts";

// Interface fixtures only. These values carry no astronomical validation.
const difference: DifferenceSummary = {
  status: "AVAILABLE", earlier_epoch_id: "earlier", later_epoch_id: "later",
  earlier_mjd: null, later_mjd: null, subtraction_order: "later - earlier",
  unit: null, variance_status: null, valid_pixel_count: 4, minimum: null,
  maximum: null, image_url: "/fixture.png", reason_codes: [], warnings: [],
};
function fixture(id: string, resource: string, status = "COMPLETED") {
  return { investigation_id: id, status, candidates: [], tracks_screened: 0, frames_used: 2,
    warnings: ["TEST_WARNING"], limitations: [], notable_tracks: [], status_counts: {},
    tracks_total: 0, difference, method: {}, detector: null,
    ...(resource === "movers" ? { track_status_counts: {} } : {}) };
}
afterEach(() => vi.unstubAllGlobals());
describe("scientific interface", () => {
  it("renders available differences and image failures", () => {
    render(<DifferenceView difference={difference} />);
    fireEvent.error(screen.getByRole("img"));
    expect(screen.getByText("Image could not be loaded.")).toBeInTheDocument();
  });
  it.each(["REJECTED", "UNAVAILABLE"])("reports %s and calibration reasons", status => {
    render(<DifferenceView difference={{ ...difference, status, reason_codes: ["CALIBRATION_UNKNOWN"] }} />);
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByText("CALIBRATION_UNKNOWN")).toBeInTheDocument();
  });
  it("handles absent products and URLs", () => {
    render(<><DifferenceView difference={null} /><PreviewImage url={null} alt="Absent" /></>);
    expect(screen.getByText("Image preview unavailable.")).toBeInTheDocument();
  });
  it.each(["COMPLETED", "UNAVAILABLE", "FAILED"])("shows screening %s independently of evidence", async status => {
    vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve(new Response(JSON.stringify(fixture("one", url.endsWith("movers") ? "movers" : "evidence", status))))));
    render(<ScienceWorkspace id="one" />);
    await screen.findByText(new RegExp("Screening " + status));
    if (status === "COMPLETED") expect(screen.getByText("No tracks qualified as possible movers.")).toBeInTheDocument();
    expect(screen.getByText("Mover screening warnings and limitations")).toBeInTheDocument();
  });
  it("rejects HTTP failures and mismatched investigations", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(new Response("bad", { status: 503 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(fixture("wrong", "movers")))));
    await expect(loadMovers("one")).rejects.toThrow("503");
    await expect(loadMovers("one")).rejects.toThrow("does not match");
  });
  it("ignores late results after investigation switching", async () => {
    let resolveOld!: (response: Response) => void;
    vi.stubGlobal("fetch", vi.fn((url: string) => url.includes("/old/")
      ? new Promise<Response>(resolve => { resolveOld = resolve; })
      : Promise.resolve(new Response(JSON.stringify(fixture("new", "movers"))))));
    const view = render(<ScienceWorkspace id="old" />);
    view.rerender(<ScienceWorkspace key="new" id="new" />);
    await screen.findByText(/Screening COMPLETED/);
    resolveOld(new Response(JSON.stringify(fixture("old", "evidence", "FAILED"))));
    await waitFor(() => expect(screen.queryByText("Evidence FAILED")).toBeNull());
  });
});

describe("evidence dialog", () => {
  it("opens, displays separate classifications, closes and restores focus", async () => {
    Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: function(this: HTMLDialogElement) { this.setAttribute("open", ""); } });
    Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value: function(this: HTMLDialogElement) { this.removeAttribute("open"); this.dispatchEvent(new Event("close")); } });
    vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve(new Response(JSON.stringify({
      ...fixture("one", url.endsWith("movers") ? "movers" : "evidence"),
      notable_tracks: [{ track_id: "test-track", statuses: ["TEST"], motion_status: "AMBIGUOUS", brightness_status: "UNAVAILABLE", reason_codes: [], limitations: [] }],
    })))));
    render(<ScienceWorkspace id="one" />);
    await screen.findByText(/Screening COMPLETED/);
    fireEvent.click(screen.getByRole("button", { name: "Open evidence" }));
    expect(screen.getByRole("dialog")).toBeVisible();
    expect(screen.getByText("Motion AMBIGUOUS")).toBeInTheDocument();
    expect(screen.getByText("Brightness UNAVAILABLE")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close evidence" }));
    expect(screen.getByRole("button", { name: "Open evidence" })).toHaveFocus();
    vi.restoreAllMocks();
  });
});
