import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function loadDemo() {
  fireEvent.change(screen.getByLabelText(/Right Ascension/), { target: { value: "269.4" } });
  fireEvent.change(screen.getByLabelText(/Declination/), { target: { value: "4.6" } });
  fireEvent.change(screen.getByLabelText(/Field-of-view radius/), { target: { value: "60" } });
  fireEvent.click(screen.getByRole("button", { name: "Load demo timeline" }));
  await screen.findByAltText(/Synthetic demo image for frame 1 of 5/);
}

describe("frontend interaction", () => {
  it("opens coordinate links directly and retains a loaded field when returning from overview", async () => {
    window.history.replaceState({}, "", "/?ra=269.4&dec=4.6&radius_arcsec=60");
    render(<App />);
    await loadDemo();
    fireEvent.change(screen.getByLabelText(/Right Ascension/), { target: { value: "12" } });
    expect(screen.getByText(/RA 269.4°/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Overview/ }));
    expect(screen.getByRole("heading", { name: /SPHEREx observations, across time/ })).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: /Start investigation/ })[0]);
    expect(screen.getByAltText(/Synthetic demo image for frame 1 of 5/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Right Ascension/)).toHaveValue("12");
  });

  it("selects dated epochs and follows history view changes", async () => {
    window.history.replaceState({}, "", "/?view=investigation");
    render(<App />);
    await loadDemo();
    fireEvent.click(screen.getByRole("button", { name: /03.*2024-06-16/ }));
    expect(screen.getByText("03 / 05")).toBeInTheDocument();
    window.history.replaceState({}, "", "/?view=overview");
    fireEvent.popState(window);
    expect(screen.getByRole("heading", { name: /SPHEREx observations, across time/ })).toBeInTheDocument();
  });
  it("shows coordinate validation feedback and writes valid values into the URL", async () => {
    window.history.replaceState({}, "", "/?view=investigation");
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Load demo timeline" }));
    expect(await screen.findByText(/0° up to/)).toBeInTheDocument();
    expect(screen.getByText(/−90° to \+90°/)).toBeInTheDocument();

    await loadDemo();
    expect(window.location.search).toContain("ra=269.4");
    expect(window.location.search).toContain("radius_arcsec=60");
    expect(screen.getByText("SYNTHETIC DATA")).toBeInTheDocument();
    expect(screen.getByText(/Jan 12, 2024/)).toBeInTheDocument();
  });

  it("supports previous, next, play, pause, and scrubbing", async () => {
    window.history.replaceState({}, "", "/?view=investigation");
    render(<App />);
    await loadDemo();

    fireEvent.click(screen.getByRole("button", { name: "Next frame" }));
    expect(screen.getByText("02 / 05")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Previous frame" }));
    expect(screen.getByText("01 / 05")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("slider", { name: "Timeline position" }), { target: { value: "3" } });
    expect(screen.getByText("04 / 05")).toBeInTheDocument();

    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "Play timeline" }));
    expect(screen.getByRole("button", { name: "Pause timeline" })).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(1200));
    expect(screen.getByText("05 / 05")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Pause timeline" }));
    expect(screen.getByRole("button", { name: "Play timeline" })).toBeInTheDocument();
  });

  it("shows a useful error when the backend cannot be reached", async () => {
    window.history.replaceState({}, "", "/?view=investigation");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Failed to fetch")));
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /Backend API/ }));
    fireEvent.change(screen.getByLabelText(/Right Ascension/), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText(/Declination/), { target: { value: "-2" } });
    fireEvent.change(screen.getByLabelText(/Field-of-view radius/), { target: { value: "30" } });
    fireEvent.click(screen.getByRole("button", { name: "Query backend" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Failed to fetch");
    await waitFor(() => expect(screen.getByText(/Check the coordinates or backend connection/)).toBeInTheDocument());
  });
});
