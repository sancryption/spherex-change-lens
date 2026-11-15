# AI Usage

Codex assisted with the Python 3.10 project setup, draft Pydantic contracts, five-target registry, IRSA TAP discovery and retrieval adapters, coverage reporting, thin FastAPI app, tests, and handoff documents. Tests were written before each behavior change and run offline by default; the opt-in live test and five-target archive queries accessed IRSA on 14 November 2026.

The recorded VOTable fixtures and in-memory FITS products used in unit tests are synthetic test inputs. The authentic Barnard's Star cutout is separate: it was retrieved from the IRSA URL recorded in its source manifest, labeled as cached, and kept in the git-ignored cache directory. Its FITS container was checked, but no science, WCS, or photometric validation was performed. The authentic timeline fixture preserves that limitation in its warning fields.

Target names and the exact WISE 0855 coordinates came from the user-provided challenge materials. Other catalogued J2000 coordinates were taken from SIMBAD and listed in [`REFERENCES.md`](REFERENCES.md). All target coverage remains `UNVERIFIED`; the draft contracts still need INT-001 review and freeze.

## Super Intelligence (SI) use, whole team (NASA Space Apps 2026 disclosure)

- **Code and data (KP / DATA):** Codex, as described above.
- **Code (Felix / backend + integration):** Claude Code (Anthropic) assisted with the FastAPI backend (investigations, timeline, artifacts, SQLite), the IRSA archive client with north-up alignment and preview rendering, wiring the SCI pipeline into `/movers` and `/evidence`, the demo pre-warm script and caches, CI changes, and tests. All changes went through pull requests reviewed by the team.
- **Demo video:** edited with Claude Code (automated screen recording of the real app, motion title scenes and captions). It carries a visible SI watermark. All sky imagery in the video is real SPHEREx data retrieved from NASA/IPAC IRSA. The voiceover is a human recording (no SI audio).
- **Images:** the landing page background illustration and the spacecraft logo were generated with ChatGPT. Both carry a visible "AI" watermark on the image itself and are labelled in the site footer. They are illustrations, not NASA photographs, and contain no NASA logos or insignia.
