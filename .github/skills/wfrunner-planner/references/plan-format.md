# Plan Format

WaterfallRunner plans are Markdown files with human-readable context and
machine-readable YAML step metadata. The schema at
`schemas/implementation-step.schema.json` is the source of truth for allowed
metadata fields.

## Heading Pattern

Each step starts with a level-three heading:

```markdown
### STEP-001 - Create parser tests
```

The parser in `tools/plan_parser.py` accepts `STEP-###` and minor
`STEP-###.###` IDs. The heading ID and title must match the YAML `id` and
`title` values exactly.

## IMPLEMENTATION Fields

Use `IMPLEMENTATION` for any step that creates, modifies, or removes files.

```yaml
schema_version: 1
id: STEP-001
title: Create parser tests
type: IMPLEMENTATION
agent: default
model: default
allowed_files:
  - tests/test_plan_parser.py
verification:
  commands:
    - "python -m pytest tests/test_plan_parser.py -v"
retry:
  max_fix_attempts: 1
```

Required fields are `schema_version`, `id`, `title`, `type`, `agent`,
`model`, `allowed_files`, `verification`, and `retry`.

## HUMAN_GATE Fields

Use `HUMAN_GATE` when execution must stop for review, approval, ambiguous
requirements, protected-file authorization, or an irreversible decision.

```yaml
schema_version: 1
id: STEP-002
title: Review parser contract
type: HUMAN_GATE
review_guidance: Confirm the parser contract before implementation continues.
```

Do not add implementation-only fields such as `agent`, `prompt`, `model`,
`allowed_files`, `verification`, or `retry` to a `HUMAN_GATE` step.

## ANALYSIS Fields

Use `ANALYSIS` for source-preserving diagnostics, evidence generation, or
model-authored reports.

```yaml
schema_version: 1
id: STEP-003
title: Analyze package smoke output
type: ANALYSIS
artifact_files:
  - .wfrunner/analysis/package-smoke.md
pre_analysis:
  commands:
    - id: package-smoke
      run: "python build.py"
      purpose: Generate packaged executable smoke evidence.
      fail_on_nonzero: true
      output_files:
        - .wfrunner/analysis/package-smoke.md
```

Do not add `allowed_files`, `verification`, or `retry` to an `ANALYSIS` step.

## Minor Step Numbering

Use minor IDs such as `STEP-004.001` only when inserting work between existing
major steps without immediately renumbering the whole plan. Minor steps must
follow their bare major step and remain contiguous within that major.

When the plan is ready for execution or publication, flatten minor steps by
renumbering all headings and YAML `id` fields to contiguous `STEP-###` values.

## `pre_analysis`

`pre_analysis` is optional diagnostic context. Commands must be read-only and
must not replace verification.

```yaml
pre_analysis:
  commands:
    - id: inspect-parser
      run: "python -m pytest tests/test_plan_parser.py -v"
      purpose: Inspect parser failures before implementation.
      fail_on_nonzero: false
      output_files:
        - .wfrunner/analysis/parser-diagnostics.txt
```

    Each command requires `id`, `run`, `purpose`, and `fail_on_nonzero`.
    Use optional `output_files` when the command generates durable evidence that
    an agent or human should inspect later.

## Validation Authority

Use `tools/plan_validator.py` through the project validation command after
editing a plan. If the schema and prose disagree, change the plan to match the
schema and validator rather than inventing local exceptions.

