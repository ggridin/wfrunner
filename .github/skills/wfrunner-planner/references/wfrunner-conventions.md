# WaterfallRunner Conventions

WaterfallRunner plans are execution contracts. Keep metadata precise, bounded, and
aligned with the orchestrator behavior.

## Defaults

Most implementation steps use:

```yaml
agent: default
model: default
```

Use another agent or model only when the plan explicitly needs that
specialized behavior.

## Review and fix agents

WaterfallRunner ships two optional agents that map onto existing step types, so a
review/fix loop needs no new step type or schema field:

- `codereview` — an `ANALYSIS` step that reviews the plan's own changes and
  writes findings to its `artifact_files`. It may use a different `model` and
  never edits source.
- `codefix` — an `IMPLEMENTATION` step that reads those findings (named in the
  task prose) and applies the smallest correct change within `allowed_files`.

Scope the review with a portable baseline (assumes auto-commit is on, so each
step commits and `base..HEAD` captures the plan's work). Record the baseline in
the **first** step:

```yaml
schema_version: 1
id: STEP-001
title: Record review baseline
type: ANALYSIS
artifact_files:
  - .wfrunner/analysis/plan-base.sha
pre_analysis:
  commands:
    - id: record-baseline
      run: "python -m tools.review_base record --file .wfrunner/analysis/plan-base.sha"
      purpose: Capture the plan's starting commit for a scoped review.
      fail_on_nonzero: true
      output_files:
        - .wfrunner/analysis/plan-base.sha
```

The `codereview` step turns that baseline into a diff and reviews it:

```yaml
schema_version: 1
id: STEP-050
title: Review the plan's changes
type: ANALYSIS
agent: codereview
model: default
artifact_files:
  - .wfrunner/analysis/STEP-050-review.md
pre_analysis:
  commands:
    - id: review-diff
      run: "python -m tools.review_base diff --base-file .wfrunner/analysis/plan-base.sha --out .wfrunner/analysis/STEP-050-review.patch"
      purpose: Produce the scoped base..HEAD diff for review.
      fail_on_nonzero: true
      output_files:
        - .wfrunner/analysis/STEP-050-review.patch
```

```yaml
schema_version: 1
id: STEP-051
title: Address review findings
type: IMPLEMENTATION
agent: codefix
model: default
allowed_files:
  - tools/parser.py
verification:
  commands:
    - "python -m pytest tests/test_parser.py -v"
retry:
  max_fix_attempts: 1
```

Notes:

- Findings are Markdown that opens with the structured `yaml` summary described
  below, then any human-readable notes needed for context. The findings file is
  read-only input for `codefix`, so it stays out of `allowed_files`.
- If git is unavailable the diff helper writes a fallback marker; the reviewer
  then reviews the union of the plan's `allowed_files`, so name those files in
  the review step's task prose.
- A review that finds nothing yields a no-op fix that still passes scope and
  verification, so the pair is safe to include by default.

### Findings file format

Use this severity rubric:

- `blocker`: correctness, data-loss, security, or scope issue that should stop
  the change from landing.
- `major`: important defect or maintainability issue that should be fixed before
  relying on the change.
- `minor`: localized improvement that is worth fixing but does not undermine the
  main behavior.
- `nit`: small clarity, style, or wording issue that is optional.

Open the report with a fenced `yaml` block in this shape:

```yaml
reviewed:
  base: .wfrunner/analysis/plan-base.sha
  patch: .wfrunner/analysis/STEP-050-review.patch
findings: 2
by_severity:
  blocker: 0
  major: 1
  minor: 1
  nit: 0
items:
  - id: REVIEW-001
    severity: major
    location: tools/parser.py:42
    problem: Parser accepts an empty step title, which later progress output cannot identify clearly.
    suggested_fix: Reject empty titles during plan parsing and cover the case with a parser test.
  - id: REVIEW-002
    severity: minor
    location: tests/test_parser.py:88
    problem: The new parser test duplicates setup already provided by a helper.
    suggested_fix: Reuse the existing plan-fragment helper to keep the fixture concise.
```

Each finding has a stable `id` so a `codefix` step can report per-finding
outcomes.

## Plan design principles

These principles govern the implementation plans this skill produces, not the
code those plans implement. Keep the guidance self-contained in this skill.

- DRY (Do not repeat yourself): move context, setup, review baselines, or
  verification rationale shared by several steps into the plan preamble or one
  shared step instead of repeating it in each step.
- KISS: prefer the fewest, simplest steps and the simplest verification that
  still bounds the work and can falsify the step.
- YAGNI: every requirement and step must trace to source material or a necessary
  validation need. Do not invent speculative steps, abstractions, or future
  phase work.
- Least Astonishment: keep plans predictable. Use contiguous IDs, conventional
  names, one YAML block per step, strict `allowed_files`, and a `HUMAN_GATE`
  immediately before each protected-path change.

## SOLID and design concerns

SOLID is a design concern, not a plan-format rule. The planner still acts as a
design guard when source material would force the plan to encode an obvious
SOLID problem.

- SRP maps to plan shape: each step should have one responsibility and a tight
  `allowed_files` list.
- OCP, LSP, ISP, and DIP describe code architecture. Do not pretend the plan can
  apply them by wording alone.
- If a SOLID concern can be addressed by pure plan decomposition, split or
  reorder the steps. If addressing it would change product design, add a
  `HUMAN_GATE` that names the concern and asks for direction instead of silently
  redesigning the product or encoding the problem.

## Protected Paths

The built-in protected paths are:

- `schemas/`
- `tools/validate_plan.py`
- `tools/run_plan.py`
- `.github/agents/`
- `.github/copilot-instructions.md`
- `prompts/`

Protected-path changes require a prior `HUMAN_GATE`. Keep that gate close to
the implementation step and describe the decision being approved.

## Verification Authority

Verification belongs to the orchestrator. Agent notes or manually run checks do
not replace the commands under:

```yaml
verification:
  commands:
    - "python -m pytest tests/test_example.py -v"
```

Choose commands that can falsify the step's work and keep them realistic for
the files in scope. The orchestrator passes each command verbatim to the current
platform's default shell; it does not normalize quoting or other shell syntax.
Write `verification.commands` to be portable across every target platform, or
use a platform-specific plan when portability is not possible.

## `allowed_files`

`allowed_files` is a strict repository-relative allowlist. Include every file
the implementation step may create or modify, including tests, docs, schemas,
and scripts. Do not include broad directories unless the step intentionally
authorizes any file under that directory.

New files must be listed before the step runs. Deletions and renames are not
allowed in Phase 1 execution.

## Retry Limits

Use a small retry limit, usually `0`, `1`, or `2`, based on the complexity of
the verification loop. Retries are for bounded fix attempts, not open-ended
implementation.

## Plan Immutability During Runs

Treat the implementation plan as immutable while a run is executing. Runtime
state belongs under `.automation/`; plan changes belong in separate, explicit
planning steps.
