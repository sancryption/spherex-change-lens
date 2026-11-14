export interface ReferenceTarget {
  target_id: string;
  name: string;
  ra: number;
  dec: number;
  category: string;
  description: string;
}

// Mirrors the repository reference catalog. Its documentation says coverage is
// pending verification; selecting a target does not imply archive availability.
export const REFERENCE_TARGETS: ReferenceTarget[] = [
  {
    target_id: "barnards-star",
    name: "Barnard's Star",
    ra: 269.45208,
    dec: 4.69339,
    category: "standard_star",
    description: "High proper motion red dwarf reference star.",
  },
  {
    target_id: "epsilon-indi-b",
    name: "Epsilon Indi B",
    ra: 331.04375,
    dec: -56.78278,
    category: "brown_dwarf",
    description: "Nearby brown dwarf candidate benchmark.",
  },
  {
    target_id: "wise-0855",
    name: "WISE 0855",
    ra: 133.79513,
    dec: -7.24514,
    category: "y_dwarf",
    description: "Cold sub-stellar object benchmark.",
  },
  {
    target_id: "rw-aurigae",
    name: "RW Aurigae",
    ra: 76.95625,
    dec: 30.40139,
    category: "yso_variable",
    description: "Variable young stellar object binary system.",
  },
  {
    target_id: "r-draconis",
    name: "R Draconis",
    ra: 248.1675,
    dec: 66.755,
    category: "mira_variable",
    description: "Mira-type pulsating long-period variable star.",
  },
];
