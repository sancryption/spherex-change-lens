# SPHEREx target coverage

This report summarizes IRSA archive metadata and recorded FITS-container checks. Science validation has not been performed. Usable coverage is not claimed; every target remains `UNVERIFIED` until the required validation evidence is recorded.

Timelines group observations by band, product family, spectral plane, and release. Exact duplicate records are counted once; conflicting or unusable observations remain with reasons. Full per-series and per-frame manifests are returned by `build_coverage_report()`; the checked-in JSON stores compact target summaries.

Visit groups split when adjacent observation times differ by more than 30 days.

| Target | Discovery | Frames | Date range | Detectors | Visit groups | Releases |
|---|---|---:|---|---|---:|---|
| Barnard's Star | COMPLETE | 363 | 2025-08-15 – 2026-09-22 | {"SPHEREx-D1": 60, "SPHEREx-D2": 62, "SPHEREx-D3": 60, "SPHEREx-D4": 60, "SPHEREx-D5": 62, "SPHEREx-D6": 59} | 3 | {"DR1": 240, "QR3": 123} |
| Epsilon Indi B | COMPLETE | 465 | 2025-04-24 – 2026-10-02 | {"SPHEREx-D1": 48, "SPHEREx-D2": 93, "SPHEREx-D3": 99, "SPHEREx-D4": 45, "SPHEREx-D5": 84, "SPHEREx-D6": 96} | 4 | {"DR1": 345, "QR3": 120} |
| WISE 0855 | COMPLETE | 258 | 2025-05-05 – 2026-05-14 | {"SPHEREx-D1": 36, "SPHEREx-D2": 48, "SPHEREx-D3": 45, "SPHEREx-D4": 36, "SPHEREx-D5": 48, "SPHEREx-D6": 45} | 3 | {"DR1": 258} |
| RW Aurigae | COMPLETE | 335 | 2025-09-01 – 2026-09-16 | {"SPHEREx-D1": 56, "SPHEREx-D2": 55, "SPHEREx-D3": 56, "SPHEREx-D4": 56, "SPHEREx-D5": 56, "SPHEREx-D6": 56} | 3 | {"DR1": 226, "QR3": 109} |
| R Draconis | COMPLETE | 2493 | 2025-04-24 – 2026-09-27 | {"SPHEREx-D1": 584, "SPHEREx-D2": 89, "SPHEREx-D3": 574, "SPHEREx-D4": 584, "SPHEREx-D5": 89, "SPHEREx-D6": 573} | 2 | {"DR1": 1638, "QR3": 855} |

## Evidence limits

- **Barnard's Star:** 362 metadata records; 1 file-validated; 0 science-validated; target status `UNVERIFIED`; usable `false`.
  - Timeline evidence: 363 found, 1 downloaded, 1 parsed, 0 compatible, 0 scientifically measured; series status `PARTIALLY_VALIDATED`.
- **Epsilon Indi B:** 465 metadata records; 0 file-validated; 0 science-validated; target status `UNVERIFIED`; usable `false`.
  - Timeline evidence: 465 found, 0 downloaded, 0 parsed, 0 compatible, 0 scientifically measured; series status `PARTIALLY_VALIDATED`.
- **WISE 0855:** 258 metadata records; 0 file-validated; 0 science-validated; target status `UNVERIFIED`; usable `false`.
  - Timeline evidence: 258 found, 0 downloaded, 0 parsed, 0 compatible, 0 scientifically measured; series status `PARTIALLY_VALIDATED`.
- **RW Aurigae:** 335 metadata records; 0 file-validated; 0 science-validated; target status `UNVERIFIED`; usable `false`.
  - Timeline evidence: 335 found, 0 downloaded, 0 parsed, 0 compatible, 0 scientifically measured; series status `PARTIALLY_VALIDATED`.
- **R Draconis:** 2493 metadata records; 0 file-validated; 0 science-validated; target status `UNVERIFIED`; usable `false`.
  - Timeline evidence: 2493 found, 0 downloaded, 0 parsed, 0 compatible, 0 scientifically measured; series status `PARTIALLY_VALIDATED`.
