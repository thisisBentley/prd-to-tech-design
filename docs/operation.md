# Operation

## Minimal no-network run

1. Set all adapters to defaults in `config/config.example.yaml`.
2. Provide requirement text manually.
3. Run Discovery if context or ideation is needed.
4. Run Delivery.
5. Review all six artifacts.
6. Manually copy `Issue_Description.md` to your tracker if desired.

## With external adapters

1. Configure read adapters.
2. Confirm authorization and scope.
3. Run Discovery.
4. Answer product questions.
5. Run Delivery.
6. Review gates and unverified items.

## With write adapters

Write adapters are never enabled by default.

A write operation must:

1. Generate a dry-run plan.
2. Show exact changes and targets.
3. Receive user confirmation for that specific plan.
4. Execute once.
5. Read back and report actual result.
6. Never alter gate conclusions because of write success/failure.
