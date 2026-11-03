# Adapters

Adapters isolate environment-specific systems from the portable core.

## Capabilities

| Capability | Purpose | Default |
|---|---|---|
| `issue-tracker` | Read/write work items | `manual` |
| `code-intelligence` | Search/read implementation evidence | `none` |
| `knowledge-source` | Search/read documents and prior work | `none` |
| `git-source` | Compare branches and read repository evidence | `none` |
| `ui-kit` | Generate/validate interaction prototypes | `neutral-html` |
| `model-provider` | Describe the hosting model/runtime | `host-agent` |

## Required principles

1. Core does not import a provider package directly.
2. Provider-specific identifiers remain inside adapter configuration.
3. Read adapters must fail closed and mark evidence unavailable.
4. Write adapters are disabled by default and require per-execution confirmation.
5. Every adapter declares capabilities and degradations.
6. No adapter stores credentials in repository files.

## Contract

Each adapter directory contains:

```text
README.md       Capability and provider notes
interface.json  Function signatures and result shapes
```

Community implementations should add:

```text
provider/<name>/
├── README.md
├── config.example.json
└── conformance.md
```

## Failure states

```text
NOT_CONFIGURED
UNAVAILABLE
UNAUTHORIZED
RATE_LIMITED
PARTIAL
ERROR
```

A failed read is not a business conclusion.
