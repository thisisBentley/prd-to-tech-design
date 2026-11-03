# Issue Tracker Adapter

Reads authoritative work-item data and, if explicitly enabled, writes changes.

Suggested providers:

- `manual` (bundled)
- `jira`
- `linear`
- `azure-devops`
- `tapd`
- `feishu-project`

The core must not depend on provider-specific custom-field names, status names, or workflow transitions.
