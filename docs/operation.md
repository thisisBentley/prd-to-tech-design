# Operation

## Minimal no-network run

1. Set all adapters to defaults in `config/config.example.yaml`.
2. Provide requirement text manually.
3. Run Discovery if context or ideation is needed.
4. Run Delivery to generate six candidate artifacts.
5. Seal the candidate revision.
6. Run all gates in an independent context.
7. If any gate fails, repair the candidate, create a new revision, seal again, and rerun all gates.
8. After all gates pass, emit `gate-outputs/` and perform final seal.
9. Manually copy `Issue_Description.md` to your tracker if desired.

## With external adapters

1. Configure read adapters.
2. Confirm authorization and scope.
3. Run Discovery.
4. Answer product questions.
5. Run Delivery.
6. Review independent final gates and unverified items.
7. Final delivery includes `gate-outputs/Final_Gate_Review.md` and six gate JSON files.

## With write adapters

Write adapters are never enabled by default.

A write operation must:

1. Generate a dry-run plan.
2. Show exact changes and targets.
3. Receive user confirmation for that specific plan.
4. Execute once.
5. Read back and report actual result.
6. Never alter gate conclusions because of write success/failure.
