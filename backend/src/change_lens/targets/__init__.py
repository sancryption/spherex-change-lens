"""Target definitions and reference catalog configuration for SPHEREx Change Lens."""

from change_lens.contracts import TargetItem

# NASA Named Reference Targets (Coverage and usability pending verification)
NASA_PRESET_TARGETS: list[TargetItem] = [
    TargetItem(
        target_id="barnards-star",
        name="Barnard's Star",
        ra=269.45208,
        dec=4.69339,
        category="standard_star",
        description="High proper motion red dwarf reference star. Usability pending verification.",
    ),
    TargetItem(
        target_id="epsilon-indi-b",
        name="Epsilon Indi B",
        ra=331.04375,
        dec=-56.78278,
        category="brown_dwarf",
        description="Nearby brown dwarf candidate benchmark. Usability pending verification.",
    ),
    TargetItem(
        target_id="wise-0855",
        name="WISE 0855",
        ra=133.79513,
        dec=-7.24514,
        category="y_dwarf",
        description="Cold sub-stellar object benchmark. Usability pending verification.",
    ),
    TargetItem(
        target_id="rw-aurigae",
        name="RW Aurigae",
        ra=76.95625,
        dec=30.40139,
        category="yso_variable",
        description="Variable Young Stellar Object binary system. Usability pending verification.",
    ),
    TargetItem(
        target_id="r-draconis",
        name="R Draconis",
        ra=248.16750,
        dec=66.75500,
        category="mira_variable",
        description="Mira-type pulsating long-period variable star. Usability pending verification.",
    ),
]
