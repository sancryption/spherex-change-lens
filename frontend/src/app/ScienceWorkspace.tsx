import { useRef, useState } from "react";
import type { DifferenceSummary } from "../contracts";
import { loadEvidence, loadMovers, useScience } from "./science";

export function Notices({ source, codes = [] }: { source: string; codes?: string[] }) {
  if (!codes.length) return null;
  return <div className="science-notices"><h3>{source}</h3><ul>{[...new Set(codes)].map(code =>
    <li key={code}><code>{code}</code>{code === "CALIBRATION_UNKNOWN" && <p>Calibration compatibility could not be established. The difference cannot be used.</p>}</li>
  )}</ul></div>;
}

export function PreviewImage({ url, alt }: { url?: string | null; alt: string }) {
  const [failed, setFailed] = useState(false);
  if (!url || failed) return <p role="status">{failed ? "Image could not be loaded." : "Image preview unavailable."}</p>;
  return <img src={url} alt={alt} onError={() => setFailed(true)} />;
}

export function DifferenceView({ difference }: { difference: DifferenceSummary | null }) {
  if (!difference) return <p role="status">Difference unavailable. No difference product was returned.</p>;
  return <div className="difference-view">
    <p role="status">Difference {difference.status}</p>
    <p>Earlier epoch {difference.earlier_epoch_id ?? "unavailable"} · Later epoch {difference.later_epoch_id ?? "unavailable"}</p>
    <p>Subtraction order {difference.subtraction_order}</p>
    {difference.status === "AVAILABLE" && <>
      <PreviewImage key={difference.image_url} url={difference.image_url} alt="Later minus earlier normalized difference" />
      <p>White indicates a positive residual, brighter in the later frame. Black indicates a negative residual, fainter in the later frame. Mid-grey can indicate zero change or masked pixels. The image shows D/√Var(D), clipped to ±5.</p>
    </>}
    <p>Unit {difference.unit ?? "unavailable"} · Variance {difference.variance_status ?? "unavailable"} · Valid pixels {difference.valid_pixel_count}</p>
    <Notices source="Difference warnings" codes={[...difference.reason_codes, ...difference.warnings]} />
  </div>;
}

export function ScienceWorkspace({ id }: { id: string }) {
  const movers = useScience(id, loadMovers);
  const evidence = useScience(id, loadEvidence);
  const [differenceVisible, setDifferenceVisible] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLButtonElement>(null);
  const m = movers.result;
  const e = evidence.result;
  return <section className="science-workspace" aria-label="Scientific analysis">
    <h2>Scientific analysis</h2>
    <p className="science-muted">Investigation {id} · Screening results require further investigation.</p>
    <div className="science-actions">
      <button aria-expanded={differenceVisible} aria-controls="difference-product" onClick={() => setDifferenceVisible(!differenceVisible)}>{differenceVisible ? "Return to observations" : "View difference"}</button>
      <button ref={opener} onClick={() => dialog.current?.showModal()}>Open evidence</button>
    </div>
    {differenceVisible && <section id="difference-product" aria-label="Difference product">
      {evidence.loading ? <p role="status">Loading difference evidence…</p> : evidence.error ? <p role="alert">{evidence.error}</p> : <DifferenceView difference={e?.difference ?? null} />}
    </section>}
    <section aria-label="Possible movers">
      <h3>Possible movers</h3>
      {movers.loading && <p role="status">Screening observations… This may take a minute.</p>}
      {movers.error && <p role="alert">{movers.error}</p>}
      {!movers.loading && <button onClick={movers.retry}>Retry screening</button>}
      {m && <>
        <p role="status">Screening {m.status} · {m.candidates.length} candidates · {m.tracks_screened} tracks screened · {m.frames_used} frames</p>
        {m.status === "COMPLETED" && m.candidates.length === 0 && <p>No tracks qualified as possible movers.</p>}
        {m.status === "UNAVAILABLE" && <p>Screening is unavailable for these observations.</p>}
        {m.status === "FAILED" && <p role="alert">Screening failed. Retry screening to try again.</p>}
        {m.candidates.map(candidate => <article className="science-track" key={candidate.track_id}>
          <h4>Possible mover · {candidate.track_id}</h4>
          <p>Displacement {candidate.displacement_arcsec} arcsec · Baseline {candidate.baseline_days} days · Positional uncertainty {candidate.uncertainty_arcsec} arcsec</p>
          <p>Control status {candidate.control_status}</p>
          <Notices source="Candidate reasons and limitations" codes={[...candidate.reason_codes, ...candidate.limitations]} />
        </article>)}
        <Notices source="Mover screening warnings and limitations" codes={[...m.warnings, ...m.limitations]} />
      </>}
    </section>
    {evidence.loading && <p role="status">Loading scientific evidence…</p>}
    {evidence.error && <p role="alert">{evidence.error}</p>}
    {!evidence.loading && <button onClick={evidence.retry}>Retry evidence</button>}
    {e && <>
      <p>Evidence {e.status}</p>
      <Notices source="Evidence warnings and limitations" codes={[...e.warnings, ...e.limitations]} />
      {e.difference && <Notices source="Difference warnings and rejection reasons" codes={[...e.difference.reason_codes, ...e.difference.warnings]} />}
    </>}
    <dialog ref={dialog} className="evidence-dialog" aria-labelledby="evidence-title" onClose={() => opener.current?.focus()}>
      <h2 id="evidence-title">Scientific evidence</h2>
      <button autoFocus onClick={() => dialog.current?.close()}>Close evidence</button>
      {evidence.loading && <p role="status">Loading evidence…</p>}
      {evidence.error && <p role="alert">{evidence.error}</p>}
      {e ? <>
        <p>Evidence {e.status} · {e.tracks_total} total tracks · {e.frames_used} frames · Detector {e.detector ?? "unavailable"}</p>
        <dl>{Object.entries(e.status_counts).map(([status, count]) => <div key={status}><dt>{status}</dt><dd>{count}</dd></div>)}</dl>
        {!e.notable_tracks.length && <p>No notable tracks were returned.</p>}
        {e.notable_tracks.map(track => <article className="science-track" key={track.track_id}>
          <h3>{track.track_id}</h3><p>Motion {track.motion_status}</p><p>Brightness {track.brightness_status}</p>
          <p>Assessments {track.statuses.join(", ")}</p>
          <Notices source="Track reasons and limitations" codes={[...track.reason_codes, ...track.limitations]} />
        </article>)}
        <Notices source="Evidence warnings and limitations" codes={[...e.warnings, ...e.limitations]} />
        <details><summary>Method metadata</summary><pre>{JSON.stringify(e.method, null, 2)}</pre></details>
      </> : !evidence.loading && <p>Evidence unavailable.</p>}
    </dialog>
  </section>;
}
