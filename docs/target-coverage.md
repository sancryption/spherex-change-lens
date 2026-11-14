# Target Coverage & Scientific Usability Baseline

**Status:** `Pending verification`  
**Warning:** The coverage, epoch frequency, and scientific usability for the five NASA targets below have not yet been queried against live archives or confirmed. Do not present these as verified observations.

---

## 1. Candidate Named Targets
The five reference targets identified for SPHEREx Change Lens are:

### 1.1 Barnard's Star
- **Scientific Rationale:** High proper motion standard star (~10.3 arcsec/year). Ideal for testing astrometric alignment and motion vector calculation.
- **Coordinates (ICRS):** RA 17h 57m 48.5s, Dec +04° 41' 36" (Epoch J2000; proper motion correction required).
- **Verification Status:** `Pending verification` against SPHEREx scan schedule and sky coverage maps.

### 1.2 Epsilon Indi B
- **Scientific Rationale:** Nearby T-dwarf binary system. Provides high-priority infrared benchmark.
- **Coordinates (ICRS):** RA 22h 04m 10.5s, Dec -56° 46' 58".
- **Verification Status:** `Pending verification`.

### 1.3 WISE 0855 (WISE J085510.83-071442.5)
- **Scientific Rationale:** Extremely cold sub-stellar object (Y dwarf). Strong infrared signature, weak optical counterpart.
- **Coordinates (ICRS):** RA 08h 55m 10.8s, Dec -07° 14' 42".
- **Verification Status:** `Pending verification`.

### 1.4 RW Aurigae
- **Scientific Rationale:** Complex young stellar object (classical T Tauri binary) with known photometric dimming and accretion variability.
- **Coordinates (ICRS):** RA 05h 07m 49.5s, Dec +30° 24' 05".
- **Verification Status:** `Pending verification`.

### 1.5 R Draconis
- **Scientific Rationale:** Long-period pulsating Mira variable star with large amplitude variations.
- **Coordinates (ICRS):** RA 16h 32m 40.2s, Dec +66° 45' 18".
- **Verification Status:** `Pending verification`.

---

## 2. Verification Protocol
1. Query the IRSA SPHEREx footprint API or SIA service for each coordinate.
2. Determine available epochs, spectral bands, signal-to-noise ratio, and edge proximity.
3. Document verified epoch timestamps and flag assessments in `data/manifests/`.
