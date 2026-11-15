import { useState } from "react";

const source = "https://www.jpl.nasa.gov/images/pia26280-first-images-from-nasas-spherex/";
const imagery = "https://d2pn8kiwq2w21t.cloudfront.net/original_images/jpegPIA26280.jpg";

export function LandingPage({ onStart }: { onStart: () => void }) {
  const [imageFailed, setImageFailed] = useState(false);
  return <div className="landing-page">
    <a className="skip-link" href="#landing-main">Skip to content</a>
    <header className="topbar"><a className="brand" href="#landing-main"><strong>SPHEREx</strong><span>Change Lens</span></a><nav aria-label="Main navigation"><a href="#how-it-works">How it works</a><button onClick={onStart}>Start investigation ↗</button></nav></header>
    <main id="landing-main">
      <section className="atlas-hero">
        <div className="hero-copy"><span className="eyebrow">An observation atlas</span><h1>SPHEREx <br />observations, <br /><span>across time.</span></h1><p>Choose a sky position and inspect repeated observations, with dates, data origin, and quality warnings in view.</p><button className="primary-button" onClick={onStart}>Start investigation <span aria-hidden="true">↗</span></button><span className="hero-footnote">One field. A sequence of observations.</span></div>
        <figure className="atlas-visual"><div className="visual-heading"><span>First light / SPHEREx</span><time>27 March 2025</time></div>{imageFailed ? <div className="image-fallback"><h2>First light from SPHEREx</h2><p>The external mission image could not load.</p><a href={source}>View the source image ↗</a></div> : <img src={imagery} alt="Six SPHEREx first-light detector images with visible colors assigned to infrared wavelengths" width="1600" height="1100" onError={() => setImageFailed(true)} />}<figcaption><span>Mission context · False-color, uncalibrated first-light imagery. Not a Change Lens query result.</span><a href={source}>Courtesy NASA/JPL-Caltech ↗</a></figcaption></figure>
      </section>
      <section className="product-section" id="how-it-works"><div className="section-intro"><span className="eyebrow">From sky position to observation</span><h2>A field of view.<br />A record of time.</h2><p>Keep the image at the center of your investigation. Move through dated frames and read their source and warnings together.</p></div><div className="product-workflow"><article><span>01 / Position</span><h3>Choose your field</h3><p>Use one of five reference targets or enter RA, Dec, and a search radius. Presets do not guarantee coverage.</p></article><article><span>02 / Time</span><h3>Follow the epochs</h3><p>Step, scrub, or play through a chronologically ordered timeline. Each frame keeps its observation date.</p></article><article><span>03 / Context</span><h3>Read the provenance</h3><p>Origin labels and quality notices stay beside the observation, including frames without an available preview.</p></article><button className="text-action" onClick={onStart}>Open the observation workspace ↗</button></div></section>
      <section className="interpretation"><h2>Observation comes first.</h2><div><p>Synthetic mode uses generated interface fixtures. Backend mode shows the origin reported for each frame and may also return synthetic data.</p><p>Visual changes alone do not establish motion or brightness variation. Scientific analysis is not available in this workspace.</p></div></section>
    </main><footer className="landing-footer"><span>SPHEREx Change Lens / Observation Atlas</span><a href="https://www.jpl.nasa.gov/jpl-image-use-policy/">Image use policy</a><span>Independent project. No NASA endorsement implied.</span></footer>
  </div>;
}
