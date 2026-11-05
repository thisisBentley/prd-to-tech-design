# AI Native Delivery

AI Native Delivery is a portable product-requirement workflow framework. It helps product teams move from an idea to a reviewed, traceable delivery bundle.

The project separates a **portable methodology core** from **environment-specific adapters**:

- The core defines the discovery process, delivery artifacts, gates, finding ledger, rerun rules, and state contract.
- Adapters provide optional integrations with issue trackers, code-search systems, knowledge bases, Git repositories, UI kits, and model hosts.
- A run can execute with no network or external service by using the bundled manual/neutral adapters.

## What it does

A complete delivery produces six primary artifacts in a fixed order:

1. `Issue_Description.md` — concise, human-readable issue summary
2. `Overview.html` — offline review page
3. `PRD_DELIVERY.md` — the sole source of business truth
4. `Prototype.html` — optional interaction prototype
5. `Gates.md` — gate results, findings, owners, and next actions
6. `Workflow.md` — execution summary, hashes, decisions, and status

After the six candidates are sealed, an independent full review runs `R0/G1/O1/U1/QA/Q1`. The final delivery also includes a separate `gate-outputs/` directory with `Final_Gate_Review.md` and one JSON result for each gate.

Discovery can optionally run first and produce:

```text
Requirement_Brief.md
.context/context-snapshot.json
.context/capability-ideation.json
.context/capability-matrix.json
```

Discovery and Delivery are independent. Discovery is not a mandatory predecessor of Delivery.

## Core ideas

- **PRD is the sole fact source.** Overview, prototype, issue description, tests, and generated summaries consume the PRD; they never redefine it.
- **Discovery is evidence based.** Claims about existing capability must identify their source and confidence.
- **Gates stay independent.** Prototype, overview, or QA failures do not silently rewrite the PRD gate.
- **Findings are root-cause based.** The same problem keeps one stable identity across artifacts and reruns.
- **Formal gates are full-copy based.** Every candidate revision is sealed and every formal review reruns all gates on that frozen copy; hashes prove the reviewed copy did not change.
- **External systems are adapters.** No company endpoint, tracker field, Git host, UI library, or private knowledge base is hard-coded in the core.
- **Read only by default.** The framework does not update external systems unless a write adapter is explicitly enabled and separately confirmed.

## Repository map

```text
.
├── core/                 Portable methodology and contracts
├── skills/               Agent-facing Discovery and Delivery skills
├── engine/               Workflow stage contracts
├── adapters/             External-system interface specifications
├── templates/            Neutral artifact templates
├── schemas/              JSON contracts for runtime artifacts
├── examples/             Synthetic, non-company demo input/output
├── tools/                Local validation and sanitization utilities
└── docs/                 Architecture and operation guides
```

## Quick start

1. Inspect `config/config.example.yaml`.
2. Read `skills/discovery/SKILL.md` and `skills/delivery/SKILL.md`.
3. Run against the synthetic input in `examples/synthetic-demo/input.md`.
4. Use only the bundled adapters for a no-network run.
5. Replace adapters only when your environment permits their use.

## Default adapter set

| Capability | Default | Result |
|---|---|---|
| Issue tracker | `manual` | Requirement text is supplied by the user |
| Code intelligence | `none` | Code-backed claims remain unverified |
| Knowledge source | `none` | No historical-reference claims are generated |
| Git source | `none` | Branch-level implementation is not asserted |
| UI kit | `neutral-html` | Produces a standalone HTML prototype |
| Model provider | `host-agent` | Uses the hosting agent/runtime |

## Safety boundary

This project is designed to be safe to run in a closed environment:

- No credentials are committed.
- No write adapter is enabled by default.
- No historical company/customer data is required.
- Synthetic examples are fictional.
- Before publishing or contributing, run `tools/sanitize_scan.py`.

## License

The repository is prepared under the MIT License. Adjust the copyright line before your first public release if you choose a different license.
