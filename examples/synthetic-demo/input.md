# DEMO-001 — Support Insight Console

## Raw requirement

Support leads at Acme Example Company cannot see why automated support conversations end without resolution. They want a simple console to identify unresolved conversation clusters and export a daily summary.

## Known facts

- Conversations have channel, customer segment, created time, resolution status, and conversation topic.
- Existing generic export creates CSV files asynchronously.
- There is no requirement to change the automation engine.
- The first release is for support leads only.

## Constraints

- Must work in a browser-based admin console.
- Must support date-range filtering.
- Must not expose customer-identifying information.
- Must not require real-time streaming.

## Non-goals

- No changes to automation logic.
- No new data warehouse.
- No customer-facing page.
