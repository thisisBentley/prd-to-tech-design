# Capability Ideation

Capability Ideation is an optional Discovery module that turns evidence into candidate solution directions. It is evidence-constrained brainstorming, not unrestricted invention.

## Question

> Which existing capabilities, patterns, or reusable combinations could plausibly address this business problem?

## Inputs

- Restated business problem
- Capability demands
- Issue history
- Knowledge documents
- Code intelligence results
- Optional Git evidence
- User-provided specialist facts

## Process

1. **Restate the business problem**
   - Actor, trigger, pain, desired outcome, constraints, and non-goals.

2. **Decompose capability demands**
   - Entry, filtering, analysis, detail, export, configuration, permission, integration, exception handling.

3. **Expand search terms**
   - Search by business intent and capability pattern, not only the feature name.

4. **Collect candidate capabilities**
   - Record source, availability, confidence, limitations, and evidence references.

5. **Compose solution options**
   - Combine capabilities into two to four candidate directions.

6. **Evaluate options**
   - Business fit, coverage, gaps, user path, data feasibility, permission fit, reuse value, risk, and evidence strength.

7. **Generate product questions**
   - Ask at most five questions that change solution direction or business outcome.

## Availability states

```text
exists_in_target_environment
historically_delivered
configuration_dependent
variant_only
runtime_unknown
not_found_in_available_sources
conflict
```

## Confidence

```text
high    Multiple independent sources agree
medium  One useful source, or sources with limited scope
low     Similar pattern only
unknown Critical evidence is absent
```

## Output limits

- At most eight candidate capabilities.
- Two to four solution options.
- At most one recommended option.
- At most five open product questions.

## Boundary

A recommendation is a hypothesis. It becomes a requirement fact only after explicit product confirmation.
