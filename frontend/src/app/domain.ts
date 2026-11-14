import type {
  CoordinateQueryRequest,
  EpochDescriptor,
  TimelineResponse,
} from "../contracts";

export type QueryParameters = CoordinateQueryRequest & { target_id?: string };

/** The latest backend contract adds provenance and reason codes to each epoch. */
export interface ObservationFrame extends EpochDescriptor {
  data_origin?: "authentic_live" | "authentic_cached" | "synthetic" | string;
  warnings?: string[];
}

export interface ObservationTimeline extends Omit<TimelineResponse, "epochs"> {
  epochs: ObservationFrame[];
}

export interface FieldErrors {
  ra?: string;
  dec?: string;
  radius_arcsec?: string;
}

export interface ValidationResult {
  values?: QueryParameters;
  errors: FieldErrors;
}

export function validateCoordinates(
  raText: string,
  decText: string,
  radiusText: string,
  targetId?: string,
): ValidationResult {
  const errors: FieldErrors = {};
  const ra = Number(raText);
  const dec = Number(decText);
  const radius = Number(radiusText);

  if (!raText.trim() || !Number.isFinite(ra) || ra < 0 || ra >= 360) {
    errors.ra = "Enter a number from 0° up to (but not including) 360°.";
  }
  if (!decText.trim() || !Number.isFinite(dec) || dec < -90 || dec > 90) {
    errors.dec = "Enter a number from −90° to +90°.";
  }
  if (
    !radiusText.trim() ||
    !Number.isFinite(radius) ||
    radius <= 0 ||
    radius > 3600
  ) {
    errors.radius_arcsec = "Enter a radius greater than 0 and no more than 3,600 arcsec.";
  }

  if (Object.keys(errors).length > 0) return { errors };
  return {
    errors,
    values: {
      ra,
      dec,
      radius_arcsec: radius,
      ...(targetId ? { target_id: targetId } : {}),
    },
  };
}

export function readQueryFromUrl(url: URL): {
  ra: string;
  dec: string;
  radius: string;
  targetId: string;
} {
  return {
    ra: url.searchParams.get("ra") ?? "",
    dec: url.searchParams.get("dec") ?? "",
    radius: url.searchParams.get("radius_arcsec") ?? "",
    targetId: url.searchParams.get("target_id") ?? "",
  };
}

export function writeQueryToUrl(url: URL, query: QueryParameters): URL {
  const updated = new URL(url);
  updated.searchParams.set("ra", String(query.ra));
  updated.searchParams.set("dec", String(query.dec));
  updated.searchParams.set("radius_arcsec", String(query.radius_arcsec));
  if (query.target_id) updated.searchParams.set("target_id", query.target_id);
  else updated.searchParams.delete("target_id");
  return updated;
}

export function sortEpochsChronologically<T extends Pick<ObservationFrame, "mjd" | "observation_time_utc">>(
  epochs: T[],
): T[] {
  return epochs
    .map((epoch, originalIndex) => ({ epoch, originalIndex }))
    .sort((left, right) => {
      const leftMjd = Number(left.epoch.mjd);
      const rightMjd = Number(right.epoch.mjd);
      if (Number.isFinite(leftMjd) && Number.isFinite(rightMjd) && leftMjd !== rightMjd) {
        return leftMjd - rightMjd;
      }
      const leftTime = Date.parse(left.epoch.observation_time_utc);
      const rightTime = Date.parse(right.epoch.observation_time_utc);
      if (Number.isFinite(leftTime) && Number.isFinite(rightTime) && leftTime !== rightTime) {
        return leftTime - rightTime;
      }
      return left.originalIndex - right.originalIndex;
    })
    .map(({ epoch }) => epoch);
}

export function formatObservationTime(timestamp: string): string {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return timestamp;
  return new Intl.DateTimeFormat("en", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  }).format(date);
}
