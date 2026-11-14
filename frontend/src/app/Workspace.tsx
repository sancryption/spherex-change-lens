import type { ReactNode } from "react";

export function CoordinatePanel({ children }: { children: ReactNode }) {
  return <aside id="coordinate-panel" className="query-panel" aria-label="Search coordinates"><span className="rail-label">Field controls · editable</span>{children}</aside>;
}

export function ObservationViewer({ children }: { children: ReactNode }) {
  return <section className="viewer-panel" aria-label="Observation timeline">{children}</section>;
}
