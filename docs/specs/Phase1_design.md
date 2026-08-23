# Phase 1 Design

## Short summary

Phase 1 uses the simplest useful WaterfallRunner contract: strict sequential execution, explicit human gates, mandatory file allowlists for implementation steps, first-class source-preserving analysis steps, optional pre-analysis, orchestrator-owned verification, limited retry, protected-file rules, and runtime state outside the implementation plan.

## Final design decisions

| Area | Phase 1 decision |
|---|---|
| Execution order | Strict document order. |
| Dependency field | No `depends_on`. Previous steps are implicit dependencies. |
| Step types | `IMPLEMENTATION`, `HUMAN_GATE`. |
| Documentation type | Removed. Documentation is an implementation step with docs in `allowed_files`. |
| Human gate field | No `human_gate.required`. Use `type: HUMAN_GATE`. |
| Review field | Removed from Phase 1 step YAML. |
| Risk field | Removed. Use explicit `HUMAN_GATE` before risky work. |
| Scope control | `allowed_files` is required for `IMPLEMENTATION`. |
| Pre-step diagnostics | Optional `pre_analysis`. |
| Success proof | Orchestrator-owned verification commands. |
| Retry | Optional bounded retry after verification failure. |
| Runtime state | Stored under configured `automation_dir` (default `.wfrunner/automation/`), not in the plan. |

## Implementation plan structure

The plan file is expected at:

| Setting | Init template value or artifact path |
|---|---|
| Plan file | Required CLI argument for `run`, `validate`, and `status`. |

Recommended top-level sections:

| Section | Purpose |
|---|---|
| Project description | Explain what is being implemented. |
| Implementation prerequisites | Human-readable assumptions before running. |
| Execution rules | Project-specific constraints for agents. |
| Requirements | Functional or technical requirements. |
| Implementation plan | Ordered list of steps. |
| Acceptance criteria | Overall completion criteria. |
| Stop conditions | Conditions requiring human intervention. |

Each step heading should have this form:

| Element | Requirement |
|---|---|
| Heading level | `###` |
| Step ID | `STEP-001`, `STEP-002.001`, etc. |
| Separator | Em dash or agreed separator. |
| Title | Must match YAML `title`. |

The YAML metadata block immediately below each step heading is the machine-readable contract for that step.

## Step metadata schema

### Common fields

All steps require:

| Field | Type | Required | Notes |
|---|---:|---:|---|
| `schema_version` | integer | Yes | Must be `1`. |
| `id` | string | Yes | Pattern: `STEP-###` or `STEP-###.###`. |
| `title` | string | Yes | Must match step heading title. |
| `type` | enum | Yes | `IMPLEMENTATION` or `HUMAN_GATE`. |

### Runtime progress state

Runtime state is stored in `<automation_dir>/progress.json` and is used for step selection and resume behavior.

Allowed runtime `state` values:

| State | Meaning |
|---|---|
| `TODO` | Step has not started in the current runtime record. |
| `READY` | Step is eligible to run and has not started yet. |
| `IN_PROGRESS` | Step started but did not finish cleanly. |
| `BLOCKED` | Step cannot continue until human intervention resolves a blocker. |
| `FAILED` | Step finished unsuccessfully and the run must stop. |
| `DONE` | Step completed successfully, or a `HUMAN_GATE` was approved. |
| `SKIPPED` | Step was intentionally skipped by human decision. |

Selection semantics:

- `DONE` and `SKIPPED` are complete states.
- `TODO` and `IN_PROGRESS` are incomplete states.
- `BLOCKED` and `FAILED` are stop states.
- If no runtime record exists yet for a step, the orchestrator should treat that step as effectively `TODO`.

### `IMPLEMENTATION` fields

`IMPLEMENTATION` steps require:

| Field | Type | Required | Notes |
|---|---:|---:|---|
| `agent` | string | Yes | Copilot custom agent name. |
| `prompt` | string | Yes | Prompt template path. |
| `model` | string | Yes | `default` is allowed. |
| `allowed_files` | array of strings | Yes | Strict allowlist for changed files. |
| `verification` | object | Yes | Commands run after implementation. |
| `retry` | object | Yes | Focused retry policy. |
| `pre_analysis` | object | No | Optional diagnostic commands before agent invocation. |

### `HUMAN_GATE` fields

`HUMAN_GATE` steps have no additional required fields beyond the common step fields.

Optional on `HUMAN_GATE`:

| Field | Type | Required | Notes |
|---|---:|---:|---|
| `description` | string | No | Human-facing explanation of why approval is needed or what must be reviewed. |
| `pre_analysis` | object | No | Optional diagnostic commands before stopping at, or auto-approving, the gate. |

`HUMAN_GATE` steps must not include structured gate metadata or agent execution fields such as `gate`, `agent`, `prompt`, `model`, `allowed_files`, `verification`, or `retry`.

### `ANALYSIS` fields

`ANALYSIS` steps require `artifact_files` and may include `pre_analysis`. They may optionally include `agent`, `prompt`, and `model` together when model-authored interpretation is needed.

`ANALYSIS` steps must not include `allowed_files`, `verification`, or `retry`. They generate evidence or reports and must leave Git-visible source state unchanged.

## `allowed_files` semantics

`allowed_files` is a strict allowlist of repository-relative paths that an `IMPLEMENTATION` step may change. Entries may be exact file paths or folder patterns ending in `/*`.

Rules:

| Rule | Behavior |
|---|---|
| Existing listed file modified | Allowed. |
| Non-existing listed file created | Allowed. |
| Unlisted file created or modified | Stop and mark failure/blockage. |
| Listed file deleted | Allowed. |
| Unlisted file deleted | Stop and mark scope violation. |
| File renamed | Allowed only when both the source and destination paths match `allowed_files`. Git rename detection represents the source as `deleted` and the destination as `renamed`. |
| Folder pattern ending in `/*` | Allows files under that repository-relative prefix, including nested files. |
| Protected file changed without prior human gate | Validation or orchestration should stop. |

## `pre_analysis` semantics

`pre_analysis` is optional.

It is used to run read-only diagnostic commands before invoking the agent. Examples include coverage reports, static analysis, benchmark baselines, or reading an existing analysis report.

Each command contract should include:

| Field | Type | Required | Notes |
|---|---:|---:|---|
| `id` | string | Yes | Stable name for logs. |
| `run` | string | Yes | Command to execute. |
| `purpose` | string | Yes | Why the analysis is being run. |
| `fail_on_nonzero` | boolean | Yes | Whether nonzero exit stops the step. |
| `output_files` | array of strings | No | Declared evidence files generated by the command. |

Rules:

- `pre_analysis` must be read-only with respect to Git-visible repository state.
- If Git tracking is available and the Git-visible change set differs after `pre_analysis`, the orchestrator stops.
- Changes limited to ignored or otherwise Git-invisible paths do not count as `pre_analysis` tree modification.
- If Git tracking is unavailable, `pre_analysis` mutation tracking is disabled rather than using filesystem timestamp inspection.
- Full output is stored under `<automation_dir>/pre-analysis/<STEP_ID>/`.
- Pre-analysis output is not passed to the agent prompt.
- Agents read declared output files when they need detailed evidence.
- `pre_analysis` is not a substitute for post-step verification.
- For `IMPLEMENTATION`, pre-analysis `FAIL` marks the step `FAILED` with failure reason code `PRE_ANALYSIS_FAILED`; `ERROR` marks it `BLOCKED`.
- For `HUMAN_GATE`, pre-analysis runs before stopping or auto-approval. With `--approve-human-gates`, `PASS` marks the gate `DONE` and continues; `FAIL` marks it `FAILED`; `ERROR` marks it `BLOCKED`.

## Verification semantics

Each `IMPLEMENTATION` step has a `verification` object.

| Field | Type | Required | Notes |
|---|---:|---:|---|
| `commands` | array of strings | Yes | Commands run by the orchestrator after agent execution. An empty list means no verification command execution is required. |

Rules:

- The orchestrator runs verification after agent execution when `commands` is non-empty.
- If `commands` is empty, the step may complete after scope checks and any other non-verification stop checks.
- If `commands` is non-empty, commands run sequentially in listed order.
- Verification succeeds only if all listed commands pass.
- Command exit codes are authoritative.
- Full command output is logged under `<automation_dir>/verification/<STEP_ID>/`.
- Large output is summarized or truncated for prompts and reports.
- If verification returns `FAIL`, the step fails unless retry is allowed.
- If verification returns `ERROR`, the step is blocked and retry is not attempted.

## Retry semantics

Each `IMPLEMENTATION` step has a `retry` object.

| Field | Type | Required | Notes |
|---|---:|---:|---|
| `max_fix_attempts` | integer | Yes | Recommended Phase 1 range: `0` or `1`. |

Rules:

- Retry is used only after verification failure.
- Retry is not used when `verification.commands` is empty because there is no verification failure signal.
- Retry invokes the same agent and prompt template as the original step.
- The retry request receives structured `failure_context`, not unbounded terminal output and not a separate fix prompt.
- The retry must respect the original `allowed_files`.
- Verification is rerun after the fix attempt.
- If verification still fails, execution stops.

## Agent result boundary

The worker-agent boundary should be machine-validated rather than prompt-only.

Rules:

- The worker must return exactly one versioned JSON result object.
- The orchestrator validates the result against a JSON schema before using it for control flow.
- The result contract should be minimal: `schema_version`, `step_id`, `status`, optional `notes`, and `stop_condition_hit` when blocked.
- A missing JSON result, malformed JSON, schema validation failure, or mismatched `step_id` is not success and is recorded as an invalid agent result.
- A schema-valid `status: FAILED` is not success; it marks the selected step `FAILED` without running verification.
- A schema-valid `status: BLOCKED` stops the run as blocked and requires `stop_condition_hit`.
- Agent-claimed `files_changed` and `commands_run` should not be part of the control contract.
- The orchestrator owns changed-file detection and verification execution.

## Gate semantics

A `HUMAN_GATE` step is an explicit pause in execution.

Rules:

- The orchestrator stops when the current step is `HUMAN_GATE`.
- If the run was started with `--approve-human-gates`, the orchestrator may mark the gate `DONE` and continue after optional pre-analysis passes.
- The run resumes only after a human explicitly approves proceeding.
- Approval is persisted only in `.automation/progress.json` by marking the gate step `DONE`.
- The implementation plan must not change while a run is active.
- If execution is stopped, including at a `HUMAN_GATE`, a human may revise the plan manually.
- Any updated plan must pass automated validation before the next run or resume attempt.
- If a human does not approve, the run may remain stopped after review or the plan may be revised manually.

## Orchestrator configuration

WaterfallRunner reads runtime configuration from `.wfrunner/wfrunner.toml`. `wfrunner run` requires this file unless `--config` points to another TOML file. `wfrunner validate` may run without config; protected-path validation then falls back to the built-in protected-path floor. The file is Git-ignored and user-local.

| Setting | Default |
|---|---|
| Configuration file | `.wfrunner/wfrunner.toml` |
| Plan file | Required CLI argument. |
| Step schema | `schemas/implementation-step.schema.json` |
| Automation directory | `.wfrunner/automation/` |
| Progress file | `<automation_dir>/progress.json` |
| Progress schema | `schemas/progress.schema.json` |
| Run log | `<automation_dir>/run-log.md` |
| Whole-plan report | `<automation_dir>/whole-plan-report.md` |
| Pre-analysis logs | `<automation_dir>/pre-analysis/` |
| Verification logs | `<automation_dir>/verification/` |
| Patch snapshots | `<automation_dir>/patches/` |
| Default model | `default` |
| Default agent | `spec-implementer` |
| Copilot command | `copilot` |
| Copilot CLI timeout | `600` seconds |
| Copilot CLI allow tools | `write`, `shell(python)`, `shell(pip)`, `shell(git)` |
| Copilot CLI deny tools | `shell(rm)`, `shell(git push)`, `shell(git reset)`, `shell(git clean)`, `shell(git commit)` |
| Git push after commit | `true` |
| Git operation timeout | `30` seconds. |
| Git push timeout | `60` seconds. |
| Pre-analysis command timeout | `300` seconds. |
| Default max fix attempts | Step-defined, normally `0` or `1`. |
| Start condition | Clean working tree before running a selected `IMPLEMENTATION` step. |
| Commit behavior | Every successful `IMPLEMENTATION` step is committed automatically. |
| Stop on failure | True. |
| Stop on human gate | True. |

## Protected-file rule

Protected paths have a non-removable built-in floor, and the `[protected_paths]` section in `.wfrunner/wfrunner.toml` can add project-specific protected paths. The init template writes the built-in floor explicitly:

| Path | Reason |
|---|---|
| `schemas/` | Plan contract. |
| `tools/validate_plan.py` | Validation guardrail. |
| `tools/run_plan.py` | Orchestration guardrail. |
| `.github/agents/` | Agent behavior. |
| `.github/copilot-instructions.md` | Global agent guidance. |
| `prompts/` | Prompt contracts. |
| `.wfrunner/wfrunner.toml` | Runtime configuration. |

The effective protected-path list is the union of the built-in floor and configured paths. Omitting `[protected_paths]`, or setting `paths = []`, does not remove the built-in floor.

A step that modifies a protected path should be immediately preceded by a `HUMAN_GATE` with a human-facing `description` explaining the change.

## Validation rules

The validator should reject:

- Missing YAML metadata blocks.
- Malformed YAML.
- Unknown fields.
- Missing required fields.
- Step metadata containing `state`.
- Invalid enum values.
- Duplicate step IDs.
- Non-contiguous step IDs.
- Out-of-order step IDs.
- Step heading and YAML `id` mismatch.
- Step heading and YAML `title` mismatch.
- `IMPLEMENTATION` without `allowed_files`.
- `IMPLEMENTATION` with empty `allowed_files` unless explicitly allowed by a later decision.
- `IMPLEMENTATION` without valid `verification` and `retry` objects.
- `HUMAN_GATE` with `gate` metadata.
- `HUMAN_GATE` with agent execution fields.
- Protected-file modification without immediately preceding `HUMAN_GATE`.

## Orchestrator lifecycle

| Order | Stage |
|---:|---|
| 1 | Validate implementation plan. |
| 2 | Load progress. |
| 3 | Select first incomplete step in file order. |
| 4 | If selected step is `HUMAN_GATE`, stop unless `--approve-human-gates` is set and optional pre-analysis passes. |
| 5 | If selected step is `ANALYSIS`, capture a baseline when possible, run declared analysis commands and optional agent interpretation, and fail if Git-visible source state changes. |
| 6 | Require clean working tree before running the selected `IMPLEMENTATION` step; if dirty, mark it `BLOCKED` with `DIRTY_WORKTREE`. |
| 7 | Run optional `pre_analysis`. |
| 8 | If Git tracking is available, confirm `pre_analysis` did not introduce Git-visible changes. |
| 9 | Invoke the configured agent for exactly one implementation step. |
| 10 | Enforce `allowed_files`. |
| 11 | Run verification commands. |
| 12 | Retry once if configured and verification failed. |
| 13 | Rerun verification after retry. |
| 14 | Update progress and logs. |
| 15 | Commit successful implementation step if configured. |
| 16 | Continue or stop based on whole-plan versus next-step mode, failure, gate, or completion. |
