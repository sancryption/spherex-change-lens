# References

## Project requirements

- `CLAUDE.md` and `SPHEREx Change Lens.pdf` in this repository — NASA challenge targets, task scope, representative contracts, and the exact WISE 0855 coordinates. These user-provided guides are the authority for the current workstream.
- [NASA Space Apps Challenge 2026](https://www.spaceappschallenge.org/2026/) — official challenge event site. The more specific challenge URL stored in the target registry is `https://www.spaceappschallenge.org/2026/challenges/planet-x-and-spherex/`; it returned a gateway error during this session, so the local user-provided guide remains the verified source for target requirements.

## Target coordinates

- [SIMBAD: Barnard's Star](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=Barnard%27s+Star) — J2000 ICRS catalog coordinates used in `data/targets/targets.json`.
- [SIMBAD: Epsilon Indi B](https://simbad.u-strasbg.fr/simbad/sim-id?Ident=Epsilon+Indi+B) — J2000 ICRS coordinates for the brown-dwarf system, rather than the nearby Epsilon Indi A star.
- [SIMBAD: RW Aur](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=RW+Aur) — J2000 ICRS catalog coordinates.
- [SIMBAD: R Dra](https://simbad.cds.unistra.fr/simbad/sim-id?Ident=R+Dra) — J2000 ICRS catalog coordinates.
- WISE 0855 coordinates are copied exactly from the user-provided implementation guide; no external coordinate source was substituted.

The registry keeps positions at the catalogued J2000 coordinates. Proper-motion propagation remains proposed in N-005 and is not implemented.

## Archive service and data

- [IRSA SPHEREx cutout tutorial](https://caltech-ipac.github.io/irsa-tutorials/spherex-cutouts/) — source for the TAP join, polygon coverage predicate, cutout URL pattern, and archive image HDU names.
- [IRSA Table Access Protocol documentation](https://irsa.ipac.caltech.edu/docs/program_interface/TAP.html) — TAP endpoint and request behavior used by `changelens.data.discovery`.
- [IRSA SPHEREx cutout tool documentation](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/cutout_tool.html) and [SPHEREx Help](https://irsa.ipac.caltech.edu/onlinehelp/spherex/help.pdf?id=418230f) — cutout URL parameters and supported field-of-view bounds enforced by the draft investigation contract.
- Live query and response evidence is retained in `data/target_queries/`; the five-target coverage and validation-level summary is in `docs/COVERAGE_REPORT.md` and `data/manifests/coverage_report.json`. The full chronological `TimelineManifest` is returned by `changelens.data.build_coverage_report()`.
- Authentic cutout provenance, source URL, size, retrieval mode, and local SHA-256 are recorded in `data/manifests/art_source_44f9301380eb92cd4ed25d29.json`. The FITS file itself is in the git-ignored `data/cached_mefs/` directory.

## Software

Runtime and development versions are pinned in `backend/pyproject.toml` and `backend/uv.lock`:

- [Python 3.10](https://docs.python.org/3.10/) — runtime.
- [uv 0.10.6](https://docs.astral.sh/uv/) — environment and lockfile management on the development machine; not a runtime dependency.
- [Pydantic 2.14.3](https://pypi.org/project/pydantic/2.14.3/) — strict boundary contracts.
- [Astropy 6.1.7](https://pypi.org/project/astropy/6.1.7/) — VOTable parsing and FITS container checks.
- [Requests 2.34.2](https://pypi.org/project/requests/2.34.2/) — bounded archive HTTP calls and streamed downloads.
- [FastAPI 0.162.5](https://pypi.org/project/fastapi/0.162.5/) — health and target endpoints.
- [Uvicorn 0.54.0](https://pypi.org/project/uvicorn/0.54.0/) — local ASGI server.
- [pytest 9.2.0](https://pypi.org/project/pytest/9.2.0/) — offline tests and opt-in live test marker.
