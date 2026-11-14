import { describe, expect, it } from "vitest";
import { readQueryFromUrl, sortEpochsChronologically, validateCoordinates, writeQueryToUrl } from "./domain";

describe("coordinate validation", () => {
  it("accepts contract boundary values and maps the search radius to radius_arcsec", () => {
    expect(validateCoordinates("0", "-90", "3600", "barnards-star")).toEqual({
      errors: {},
      values: { ra: 0, dec: -90, radius_arcsec: 3600, target_id: "barnards-star" },
    });
    expect(validateCoordinates("359.999", "90", "30").values).toEqual({
      ra: 359.999,
      dec: 90,
      radius_arcsec: 30,
    });
  });

  it("rejects out-of-range, empty, and nonnumeric values", () => {
    const result = validateCoordinates("360", "-90.1", "0");
    expect(result.values).toBeUndefined();
    expect(result.errors.ra).toMatch(/360/);
    expect(result.errors.dec).toMatch(/−90/);
    expect(result.errors.radius_arcsec).toMatch(/3,600/);
    expect(Object.keys(validateCoordinates("", "north", "many").errors)).toHaveLength(3);
  });
});

describe("coordinate URL parameters", () => {
  it("writes and reads the documented query values", () => {
    const url = writeQueryToUrl(new URL("https://example.test/explorer?keep=1"), {
      ra: 12.5,
      dec: -3,
      radius_arcsec: 90,
      target_id: "wise-0855",
    });
    expect(url.searchParams.get("keep")).toBe("1");
    expect(readQueryFromUrl(url)).toEqual({ ra: "12.5", dec: "-3", radius: "90", targetId: "wise-0855" });
  });
});

describe("timeline ordering", () => {
  it("sorts observation epochs by MJD while keeping ties stable by timestamp", () => {
    const epochs = [
      { epoch_id: "late", mjd: 20, observation_time_utc: "2024-01-03T00:00:00Z" },
      { epoch_id: "first-tie", mjd: 10, observation_time_utc: "2024-01-01T00:00:00Z" },
      { epoch_id: "second-tie", mjd: 10, observation_time_utc: "2024-01-02T00:00:00Z" },
    ];
    expect(sortEpochsChronologically(epochs).map((epoch) => epoch.epoch_id)).toEqual([
      "first-tie",
      "second-tie",
      "late",
    ]);
  });
});
