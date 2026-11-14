# Data Flag & Masking Policy

**Status:** `Pending implementation` & `Decision required`  
**Workstream:** SCI / DATA

---

## 1. Purpose
The SPHEREx detector arrays produce bit-level data quality flags identifying cosmic rays, saturation, bad pixels, dead pixels, and stray light artifacts. This policy dictates how flags are propagated and surfaced to users.

## 2. Bitmask Classification Strategy

| Bit Value | Description | Pipeline Action | UI Presentation |
|---|---|---|---|
| `0x0001` | Saturated pixel | Exclude from difference & photometry | Red overlay, warning icon |
| `0x0002` | Cosmic ray hit | Exclude from epoch analysis | Yellow overlay |
| `0x0004` | Known bad/dead pixel | Interpolate or mask out | Grey overlay |
| `0x0008` | Near detector edge | Mark with warning tag | Edge boundary line |
| `0x0010` | Stray light / Glint | Flag epoch as degraded | Warning banner in timeline |

## 3. Strict Quality Propagation Rules
1. **Never Silently Discard Flags:** Any pixel masked in the input FITS must remain flagged in all derived difference and preview products.
2. **Conservative Difference Masking:** In difference images ($I_{\text{diff}} = I_A - I_B$), a pixel is marked invalid if flagged in *either* image $A$ or image $B$.
3. **User Transparency:** The user must be able to toggle flag masks on/off interactively in the image viewer to inspect underlying data.
