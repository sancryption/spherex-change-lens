import React from "react";
import "../styles/main.css";

export const App: React.FC = () => {
  return (
    <div className="scaffold-container">
      <header className="scaffold-header">
        <h1>SPHEREx Change Lens</h1>
        <p>NASA Space Apps Challenge 2026</p>
        <span className="scaffold-status">
          Repository Scaffolding Status: Application Features Not Implemented Yet
        </span>
      </header>

      <section className="scaffold-section">
        <h2>Architecture Boundaries</h2>
        <p>
          The repository foundation and contracts are initialized. Interactive UI features,
          observation timeline scrubbers, difference viewers, and evidence drawers will be
          implemented in subsequent engineering phases.
        </p>

        <div className="scaffold-grid">
          <div className="scaffold-card">
            <h3>Frontend (FE)</h3>
            <p>React + TypeScript + Vite baseline ready for UI feature implementation.</p>
          </div>
          <div className="scaffold-card">
            <h3>Backend (BE)</h3>
            <p>FastAPI application factory and Pydantic contracts configured.</p>
          </div>
          <div className="scaffold-card">
            <h3>Scientific (SCI)</h3>
            <p>Pipeline module placeholders and validation boundaries established.</p>
          </div>
        </div>
      </section>
    </div>
  );
};

export default App;
