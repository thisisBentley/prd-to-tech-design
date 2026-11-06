# Agent Runtime Adapter

This adapter describes the minimum interface required to run producer and reviewer roles in separate contexts.

The core does not require a specific vendor. It requires:

- separate contexts for producer and reviewer;
- frozen artifact inputs with hashes;
- structured JSON outputs;
- no reviewer write access to candidate artifacts;
- a deterministic Gatekeeper outside the LLM.

A host can map this interface to subagents, processes, CI jobs, or another orchestration runtime.
