import { useEffect, useRef, useState, type FormEvent } from "react";
import "../styles/main.css";
import { LandingPage } from "./LandingPage";
import { CoordinatePanel, ObservationViewer } from "./Workspace";
import {
  formatObservationTime,
  readQueryFromUrl,
  validateCoordinates,
  writeQueryToUrl,
  type FieldErrors,
  type QueryParameters,
} from "./domain";
import { REFERENCE_TARGETS } from "./targets";
import { ApiError, loadApiTimeline, loadSyntheticTimeline } from "./timeline";
import type { ObservationFrame, ObservationTimeline } from "./domain";

type DataMode = "synthetic" | "api";
type RequestState = "idle" | "loading" | "ready" | "empty" | "error";

function initialFormValues() {
  const params = readQueryFromUrl(new URL(window.location.href));
  return {
    ra: params.ra,
    dec: params.dec,
    radius: params.radius,
    targetId: params.targetId,
  };
}

export default function App() {
  const [view, setView] = useState(() => viewFromUrl());
  const [editing, setEditing] = useState(true);
  const [loadedQuery, setLoadedQuery] = useState<QueryParameters | null>(null);
  const mainRef = useRef<HTMLElement>(null);
  function navigate(next: "overview" | "investigation") {
    const url = new URL(window.location.href);
    url.searchParams.set("view", next);
    window.history.pushState({}, "", url);
    setView(next);
    setIsPlaying(false);
  }
  useEffect(() => {
    const restore = () => { setView(viewFromUrl()); setForm(initialFormValues()); setIsPlaying(false); };
    window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, []);
  useEffect(() => { mainRef.current?.focus(); }, [view]);
  const [form, setForm] = useState(initialFormValues);
  const [mode, setMode] = useState<DataMode>("synthetic");
  const [timeline, setTimeline] = useState<ObservationTimeline | null>(null);
  const [requestState, setRequestState] = useState<RequestState>("idle");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [hasAttemptedSubmit, setHasAttemptedSubmit] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const requestNumber = useRef(0);
  const frames = timeline?.epochs ?? [];
  const selectedFrame = frames[selectedIndex];

  useEffect(() => {
    if (!isPlaying || requestState !== "ready" || frames.length < 2) return;
    const timer = window.setInterval(() => {
      setSelectedIndex((current) => (current + 1) % frames.length);
    }, 1100);
    return () => window.clearInterval(timer);
  }, [frames.length, isPlaying, requestState]);

  function updateForm(next: typeof form) {
    setForm(next);
    if (hasAttemptedSubmit) {
      setFieldErrors(validateCoordinates(next.ra, next.dec, next.radius, next.targetId).errors);
    }
  }

  function setCoordinateField(field: "ra" | "dec" | "radius", value: string) {
    updateForm({ ...form, [field]: value, targetId: "" });
  }

  function chooseTarget(targetId: string) {
    const target = REFERENCE_TARGETS.find((item) => item.target_id === targetId);
    updateForm(
      target
        ? {
            ra: String(target.ra),
            dec: String(target.dec),
            radius: form.radius || "60",
            targetId: target.target_id,
          }
        : { ...form, ra: "", dec: "", targetId: "" },
    );
  }

  async function submitQuery(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setHasAttemptedSubmit(true);
    const validation = validateCoordinates(form.ra, form.dec, form.radius, form.targetId);
    setFieldErrors(validation.errors);
    setErrorMessage("");
    setIsPlaying(false);
    if (!validation.values) return;

    const query: QueryParameters = validation.values;
    const updatedUrl = writeQueryToUrl(new URL(window.location.href), query);
    window.history.replaceState({}, "", updatedUrl);
    const currentRequest = ++requestNumber.current;
    setTimeline(null);
    setSelectedIndex(0);
    setRequestState("loading");

    try {
      const result =
        mode === "synthetic"
          ? await loadSyntheticTimeline(query)
          : await loadApiTimeline(query);
      if (currentRequest !== requestNumber.current) return;
      setTimeline(result);
      setLoadedQuery(query);
      setEditing(result.epochs.length === 0);
      setRequestState(result.epochs.length > 0 ? "ready" : "empty");
    } catch (error) {
      if (currentRequest !== requestNumber.current) return;
      setRequestState("error");
      setErrorMessage(
        error instanceof ApiError
          ? `${error.message}${error.code ? ` (${error.code})` : ""}${error.requestId ? ` · Request ${error.requestId}` : ""}`
          : error instanceof Error
            ? error.message
            : "The timeline could not be loaded. Try again.",
      );
    }
  }

  function changeMode(nextMode: DataMode) {
    ++requestNumber.current;
    setLoadedQuery(null);
    setEditing(true);
    setMode(nextMode);
    setTimeline(null);
    setRequestState("idle");
    setErrorMessage("");
    setIsPlaying(false);
    setSelectedIndex(0);
  }

  function togglePlayback() {
    if (!isPlaying && selectedIndex >= frames.length - 1) setSelectedIndex(0);
    setIsPlaying((current) => !current);
  }

  function moveFrame(delta: number) {
    setIsPlaying(false);
    setSelectedIndex((current) => Math.min(frames.length - 1, Math.max(0, current + delta)));
  }

  const submitLabel = mode === "synthetic" ? "Load demo timeline" : "Query backend";

  if (view === "overview") return <LandingPage onStart={() => navigate("investigation")} />;
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">Skip to investigation</a>
      <header className="topbar"><button className="brand" onClick={() => navigate("overview")}><strong>SPHEREx</strong><span>Change Lens</span></button><span className="workspace-label">/ Investigation</span><button className="overview-link" onClick={() => navigate("overview")}>Overview ↗</button></header>
      <main id="main" className="workspace" tabIndex={-1} ref={mainRef}>
        <div className="workspace-heading"><div><span className="eyebrow">Observation atlas</span><h1>Investigate a field.</h1></div><div className="source-switch" role="group" aria-label="Data source"><button aria-pressed={mode === "synthetic"} onClick={() => changeMode("synthetic")}>Synthetic demo</button><button aria-pressed={mode === "api"} onClick={() => changeMode("api")}>Backend API</button></div></div>
        <div className={`workspace-grid ${editing ? "is-editing" : "is-loaded"}`}>
          <CoordinatePanel>
            <div className="panel-heading">
              <div className="panel-step">01</div>
              <div><h2>Choose a field</h2><p>Set the sky coordinates to explore.</p></div>
            </div>

            <form onSubmit={submitQuery} noValidate>
              <label className="field-label" htmlFor="target">Reference target <span className="optional">OPTIONAL</span></label>
              <select id="target" value={form.targetId} onChange={(event) => chooseTarget(event.target.value)}>
                <option value="">Custom coordinates</option>
                {REFERENCE_TARGETS.map((target) => (
                  <option key={target.target_id} value={target.target_id}>{target.name}</option>
                ))}
              </select>
              <p className="field-hint">Catalog entries are provided for convenience; coverage is unverified.</p>

              <div className="coordinate-grid">
                <div>
                  <label className="field-label" htmlFor="ra">Right Ascension <span className="unit">deg</span></label>
                  <input id="ra" inputMode="decimal" autoComplete="off" placeholder="e.g. 269.45208" value={form.ra} aria-invalid={Boolean(fieldErrors.ra)} aria-describedby={fieldErrors.ra ? "ra-error" : undefined} onChange={(event) => setCoordinateField("ra", event.target.value)} />
                  {fieldErrors.ra && <p className="field-error" id="ra-error">{fieldErrors.ra}</p>}
                </div>
                <div>
                  <label className="field-label" htmlFor="dec">Declination <span className="unit">deg</span></label>
                  <input id="dec" inputMode="decimal" autoComplete="off" placeholder="e.g. 4.69339" value={form.dec} aria-invalid={Boolean(fieldErrors.dec)} aria-describedby={fieldErrors.dec ? "dec-error" : undefined} onChange={(event) => setCoordinateField("dec", event.target.value)} />
                  {fieldErrors.dec && <p className="field-error" id="dec-error">{fieldErrors.dec}</p>}
                </div>
              </div>

              <label className="field-label" htmlFor="radius">Field-of-view radius <span className="unit">arcsec</span></label>
              <input id="radius" inputMode="decimal" autoComplete="off" placeholder="60" value={form.radius} aria-invalid={Boolean(fieldErrors.radius_arcsec)} aria-describedby={fieldErrors.radius_arcsec ? "radius-error" : "radius-hint"} onChange={(event) => setCoordinateField("radius", event.target.value)} />
              {fieldErrors.radius_arcsec ? <p className="field-error" id="radius-error">{fieldErrors.radius_arcsec}</p> : <p className="field-hint" id="radius-hint">Sent as <code>radius_arcsec</code> (a radius, not full diameter).</p>}

              <button className="primary-button" type="submit" disabled={requestState === "loading"}>
                {requestState === "loading" ? <><span className="button-spinner" /> Loading timeline…</> : <>{submitLabel}<span aria-hidden="true">↗</span></>}
              </button>
              {mode === "synthetic" ? (
                <div className="mode-note synthetic-note"><span aria-hidden="true">✳</span><p><strong>Generated demo data</strong><br />Frames are locally generated interface fixtures, not NASA observations.</p></div>
              ) : (
                <div className="mode-note api-note"><span aria-hidden="true">↗</span><p><strong>Backend connection</strong><br />Queries the documented API. Returned provenance is shown with each frame.</p></div>
              )}
            </form>
          </CoordinatePanel>

          <ObservationViewer>
            <div className="loaded-context"><div><span className="eyebrow">Loaded field</span><h2>{loadedQuery ? (REFERENCE_TARGETS.find(t => t.target_id === loadedQuery.target_id)?.name ?? "Custom sky position") : "No field loaded"}</h2><p className="coordinate-value">{loadedQuery ? `RA ${loadedQuery.ra}° / Dec ${loadedQuery.dec}° / Radius ${loadedQuery.radius_arcsec}″` : "Submit a field to begin an observation timeline."}</p></div><button className="edit-field" onClick={() => { setEditing(!editing); if (!editing) requestAnimationFrame(() => document.getElementById("target")?.focus()); }} aria-expanded={editing} aria-controls="coordinate-panel">{editing ? "Close field controls" : "Edit field"}</button></div><div className="viewer-topline">
              <div className="viewer-title">
                <div className="panel-step">02</div>
                <div><h2>Observation timeline</h2><p>{timeline ? `${frames.length} ${frames.length === 1 ? "frame" : "frames"} · ordered by observation date` : "Load a field to view its observations."}</p></div>
              </div>
              {timeline && <div className={mode === "synthetic" ? "provenance-badge synthetic-badge" : "provenance-badge api-badge"}>{mode === "synthetic" ? "SYNTHETIC DATA" : "API DATA"}</div>}
            </div>

            <div className={`image-stage ${requestState === "idle" ? "stage-idle" : ""}`}>
              {requestState === "idle" && <div className="empty-stage"><span className="section-number">Observation viewer</span><h3>Choose where to look.</h3><p>Enter coordinates to load a generated demo timeline or query the connected backend.</p><span className="empty-caption">RA · DEC · SEARCH RADIUS</span></div>}
              {requestState === "loading" && <div className="state-message" role="status"><span className="large-spinner" /><h3>Finding observations</h3><p>Loading the timeline for this field…</p></div>}
              {requestState === "error" && <div className="state-message error-state" role="alert"><div className="state-symbol">!</div><h3>Couldn’t load this timeline</h3><p>{errorMessage}</p><span>Check the coordinates or backend connection and try again.</span></div>}
              {requestState === "empty" && <div className="state-message" role="status"><div className="state-symbol quiet-symbol">∅</div><h3>No observations found</h3><p>The service returned no frames for this field.</p><span>Try a different target or a wider search radius.</span></div>}
              {requestState === "ready" && selectedFrame && <FrameDisplay frame={selectedFrame} index={selectedIndex} total={frames.length} mode={mode} />}
            </div>

            <div className="frame-details" aria-live="polite">
              <div>
                <div className="detail-label">OBSERVATION TIME <span className="utc-label">UTC</span></div>
                <strong className="timestamp">{selectedFrame ? formatObservationTime(selectedFrame.observation_time_utc) : "—"}</strong>
              </div>
              <div className="frame-meta"><div><span className="detail-label">QUALITY</span><strong>{selectedFrame ? (selectedFrame.quality_warning || selectedFrame.warnings?.length ? "See notices" : "No warnings reported") : "Unavailable"}</strong></div>
                <div><span className="detail-label">BAND</span><strong>{selectedFrame?.band_id ?? "—"}</strong></div>
                <div><span className="detail-label">FRAME</span><strong>{selectedFrame ? `${String(selectedIndex + 1).padStart(2, "0")} / ${String(frames.length).padStart(2, "0")}` : "—"}</strong></div>
              </div>
            </div>


            <EpochRail frames={frames} selected={selectedIndex} select={(index) => { setIsPlaying(false); setSelectedIndex(index); }} />
            <div className="player-controls" aria-label="Timeline playback controls">
              <div className="transport-controls">
                <button type="button" className="transport-button" aria-label="Previous frame" disabled={frames.length === 0 || selectedIndex === 0 || requestState !== "ready"} onClick={() => moveFrame(-1)}>‹</button>
                <button type="button" className="play-button" aria-label={isPlaying ? "Pause timeline" : "Play timeline"} disabled={frames.length < 2 || requestState !== "ready"} onClick={togglePlayback}>{isPlaying ? <span className="pause-glyph" /> : <span className="play-glyph" />}</button>
                <button type="button" className="transport-button" aria-label="Next frame" disabled={frames.length === 0 || selectedIndex >= frames.length - 1 || requestState !== "ready"} onClick={() => moveFrame(1)}>›</button>
              </div>
              <div className="scrubber-wrap">
                <div className="scrubber-labels"><span>EARLIEST</span><span>{frames.length ? `${frames.length} OBSERVATIONS` : "TIMELINE"}</span><span>LATEST</span></div>
                <input aria-label="Timeline position" className="scrubber" type="range" min={0} max={Math.max(0, frames.length - 1)} step={1} value={selectedIndex} disabled={requestState !== "ready" || frames.length < 2} onChange={(event) => { setIsPlaying(false); setSelectedIndex(Number(event.target.value)); }} />
                <div className="tick-row" aria-hidden="true">{frames.map((frame) => <span key={frame.epoch_id} />)}</div>
              </div>
              <span className="playback-rate">1×</span>
            </div>
            {selectedFrame && <FrameWarnings frame={selectedFrame} />}
          </ObservationViewer>
        </div>


        <footer className="workspace-footer">SPHEREx Change Lens · Coordinates in decimal degrees · Times in UTC</footer>
      </main>
    </div>
  );
}

function viewFromUrl(): "overview" | "investigation" {
  const params = new URLSearchParams(window.location.search);
  if (params.get("view") === "overview") return "overview";
  return params.get("view") === "investigation" || params.has("ra") || params.has("dec") ? "investigation" : "overview";
}

function EpochRail({ frames, selected, select }: { frames: ObservationFrame[]; selected: number; select: (index: number) => void }) {
  return <div className="epoch-navigation"><div className="epoch-heading"><h3>Observation epochs</h3><span>Even spacing shows frame order, not elapsed time.</span></div><div className="epoch-rail">{frames.length ? frames.map((frame, index) => <button key={frame.epoch_id} aria-pressed={selected === index} onClick={() => select(index)}><span>{String(index + 1).padStart(2, "0")}{selected === index ? " · Selected" : ""}</span><time dateTime={frame.observation_time_utc}>{frame.observation_time_utc.slice(0, 10)}</time></button>) : <p>Dates will appear when a timeline is loaded.</p>}</div></div>;
}

function FrameDisplay({ frame, index, total, mode }: { frame: ObservationFrame; index: number; total: number; mode: DataMode }) {
  if (!frame.preview_url) {
    return <div className="missing-preview" role="status"><div className="missing-icon">▧</div><h3>Preview unavailable</h3><p>This observation is in the timeline, but the service did not provide an image preview.</p>{frame.data_origin && <span>Data origin: {frame.data_origin.replaceAll("_", " ")}</span>}</div>;
  }
  return (
    <div className="image-wrap">
      <img src={frame.preview_url} alt={`${mode === "synthetic" ? "Synthetic demo" : "Observation"} image for frame ${index + 1} of ${total}, ${frame.observation_time_utc}`} />
      <div className="image-overlay"><span className="image-index">FRAME {String(index + 1).padStart(2, "0")} <span>/ {String(total).padStart(2, "0")}</span></span><span className="image-origin">{mode === "synthetic" ? "GENERATED FIXTURE" : (frame.data_origin ?? "ORIGIN NOT REPORTED").replaceAll("_", " ").toUpperCase()}</span></div>
    </div>
  );
}

function FrameWarnings({ frame }: { frame: ObservationFrame }) {
  const warnings = frame.warnings ?? [];
  if (!frame.quality_warning && warnings.length === 0) return null;
  return <div className="warning-list" aria-label="Frame warnings">{frame.quality_warning && <span className="warning-chip">Quality warning</span>}{warnings.map((warning) => <span className="warning-chip" key={warning}>{warning}</span>)}</div>;
}
