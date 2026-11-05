# Synthetic Demo Expected Artifacts

This example can run entirely with the default adapters:

- Issue tracker: manual (`input.md`)
- Code intelligence: none
- Knowledge source: none
- Git source: none
- UI kit: neutral-html

Expected outputs:

```text
00-discovery/
├── Requirement_Brief.md
└── .context/
    ├── context-snapshot.json
    ├── capability-ideation.json
    └── capability-matrix.json

01-delivery/
├── Issue_Description.md
├── Overview.html
├── PRD_DELIVERY.md
├── Prototype.html
├── Gates.md
├── Workflow.md
└── gate-outputs/
    ├── Final_Gate_Review.md
    ├── R0.json
    ├── G1.json
    ├── O1.json
    ├── U1.json
    ├── QA.json
    └── Q1.json
```

Expected characteristics:

- Current-state claims remain `runtime_unknown` because code intelligence is unavailable.
- No historical capability is asserted.
- The prototype is standalone neutral HTML.
- Issue description has exactly three sections.
- PRD includes empty, failure, permission, export, and privacy boundaries.
- Six candidate artifacts are sealed before the formal review.
- Each formal review runs all six gates in an independent context.
- Failed revisions are repaired, resealed, and fully reviewed again.
- Final delivery includes the final gate review and six individual gate JSON files.
