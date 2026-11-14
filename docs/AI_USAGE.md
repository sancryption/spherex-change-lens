# AI Usage

Codex assisted with the Python 3.10 project setup, draft Pydantic contracts, five-target registry, IRSA TAP discovery and retrieval adapters, coverage reporting, thin FastAPI app, tests, and handoff documents. Tests were written before each behavior change and run offline by default; the opt-in live test and five-target archive queries accessed IRSA on 14 November 2026.

The recorded VOTable fixtures and in-memory FITS products used in unit tests are synthetic test inputs. The authentic Barnard's Star cutout is separate: it was retrieved from the IRSA URL recorded in its source manifest, labeled as cached, and kept in the git-ignored cache directory. Its FITS container was checked, but no science, WCS, or photometric validation was performed. The authentic timeline fixture preserves that limitation in its warning fields.

Target names and the exact WISE 0855 coordinates came from the user-provided challenge materials. Other catalogued J2000 coordinates were taken from SIMBAD and listed in [`REFERENCES.md`](REFERENCES.md). All target coverage remains `UNVERIFIED`; the draft contracts still need INT-001 review and freeze.
