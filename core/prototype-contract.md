# Prototype Contract Preflight

Prototype Contract Preflight runs before the full Delivery Review Group for Prototype routes.

It checks both:

1. deterministic structure and runtime facts;
2. semantic alignment between the PRD and the Prototype.

## Visible Interaction Contract

A visible interaction is complete only when all are evidenced:

```text
visibleLabel
+ clickable
+ targetView
+ contextPreserved
+ runtimeClean
```

A click handler without a visible label is not a complete implementation of a PRD requirement such as “provide a visible View Logs entry”.

## Runtime PASS

Runtime `PASS` requires zero unhandled console errors, page errors, rejected promises and resource-load errors. If required assertions pass while unrelated runtime errors remain, the result is `INCOMPLETE` or `NEEDS_FIX`, not `PASS`.
