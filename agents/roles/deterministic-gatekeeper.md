# Deterministic Gatekeeper

## Mission

Mechanically decide whether the workflow may become READY.

This is a program, not an LLM.

## It verifies

- required handoffs and reviews exist;
- every review targets the latest revision;
- producer and reviewer differ;
- reviews use independent contexts;
- accepted reviews contain checks and evidence;
- blocking counts and findings are consistent;
- all Decision Cards are closed;
- no open escalation exists;
- final technical handoff and required review chain are complete.

## It cannot

- interpret business intent;
- repair evidence;
- accept a prose explanation for a failed check;
- turn `INCOMPLETE`, `RETURNED` or `BLOCKED` into `READY`.
