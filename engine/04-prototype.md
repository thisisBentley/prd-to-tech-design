# Stage 04 · Prototype

## Goal

Represent user-visible interaction required by the PRD.

## Trigger

Generate only when at least one of these changes:

- Page or entry
- Operation path
- User-visible state
- Official copy
- Field visibility, validation, or feedback
- Permission, disabled, failure, or recovery result

## Neutral HTML fallback

The default `neutral-html` UI kit produces a standalone HTML file with no private component library or network dependency.

## Metadata

```html
<meta name="source-prd" content="PRD_DELIVERY.md">
<meta name="source-prd-sha256" content="...">
<meta name="ui-kit" content="neutral-html">
```

## U1 checks

- Entry-to-result path is represented
- Critical branches and exceptions are represented
- Fields and copy match the PRD
- State, permission, disabled, and failure outcomes are represented
- No new business rules are introduced
