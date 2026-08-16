# Phase 1 API and Data Contracts

## Short summary

This document defines the machine-facing contracts for Phase 1. It intentionally avoids implementation code. The goal is to make the validator, orchestrator, prompt templates, runtime files, and agent boundaries precise enough to implement and test.

## Contract overview

| Contract | Producer | Consumer |
|---|---|---|
| Implementation plan | Human + AI planning workflow | Validator, orchestrator, agent prompts |
| Step metadata | Plan author | Validator, orchestrator |
| Orchestrator CLI | Human/operator | `tools/wfrunner.py` |
| Pre-analysis result | Orchestrator | Progress, logs, report |
| Verification result | Orchestrator | Retry prompt, progress, report |
| Agent invocation request | Orchestrator | Copilot CLI custom agent |
| Agent result | Copilot CLI custom agent | Orchestrator, logs |
| Progress file | Orchestrator | Orchestrator resume logic, human review |
| Run log | Orchestrator | Human review |
| Whole-plan report | Orchestrator | Human review |

## Configuration file contract

WaterfallRunner reads runtime configuration from `.wfrunner/wfrunner.toml`. This file is Git-ignored and user-local.

| Item | Contract |
|---|---|
| File path | `.wfrunner/wfrunner.toml` |
| Format | TOML |
| Required for `wfrunner run` | Yes. If neither `--config` nor the default file exists, `run` fails with an actionable configuration error. |
| Required for `wfrunner validate` | No. If config is absent, validation skips protected-path checks. |
| Git status | Git-ignored (`.wfrunner/` is in `.gitignore`). |
| Protected | Yes. `.wfrunner/wfrunner.toml` is part of the built-in protected-path floor. |

Top-level keys written by the init template:

| Key | Type | Init template value | Notes |
|---|---:|---|---|
| `default_model` | string | `"default"` | Default model for agent invocation. |
| `automation_dir` | string | `".wfrunner/automation"` | Directory for runtime artifacts. |
| `copilot_command` | string | `"copilot"` | Copilot CLI executable. |
| `default_agent` | string | `"default.wfrunner"` | Default agent name. |

Optional sections:

| Section | Purpose |
|---|---|
| `[copilot_cli]` | Copilot CLI tool permissions and timeout. |
| `[protected_paths]` | Additional protected path prefixes or exact matches. |
| `[git]` | Git commit/push behavior. |

### `[copilot_cli]` section

| Key | Type | Init template value | Notes |
|---|---:|---|---|
| `timeout_seconds` | integer | `600` | Subprocess timeout for agent invocation. |
| `allow_tools` | array of strings | `["write", "shell(python)", "shell(pip)", "shell(git)"]` | `--allow-tool` flags passed to CLI. |
| `deny_tools` | array of strings | `["shell(rm)", "shell(git push)", "shell(git reset)", "shell(git clean)", "shell(git commit)"]` | `--deny-tool` flags passed to CLI. |

### `[protected_paths]` section

| Key | Type | Init template value | Notes |
|---|---:|---|---|
| `paths` | array of strings | `["schemas/", "tools/validate_plan.py", "tools/run_plan.py", ".github/agents/", ".github/copilot-instructions.md", "prompts/", ".wfrunner/wfrunner.toml"]` | Additional protected path prefixes or exact matches. Effective protected paths are the union of configured paths and the built-in floor. |

### `[git]` section

| Key | Type | Init template value | Notes |
|---|---:|---|---|
| `push_required` | boolean | `true` | Whether `git push` runs after each automated commit. |

Additional top-level timeout keys:

| Key | Type | Init template value | Notes |
|---|---:|---|---|
| `git_timeout_seconds` | integer | `30` | Timeout for local Git operations such as status/add/commit. |
| `git_push_timeout_seconds` | integer | `60` | Timeout for `git push`. |
| `pre_analysis_timeout_seconds` | integer | `300` | Timeout for each pre-analysis command. |

## Implementation-plan contract

| Item | Contract |
|---|---|
| File path | Required positional path for `run`, `validate`, and `status`. |
| Step ordering | Strict file order. |
| Step IDs | Contiguous ascending major IDs with optional contiguous minor IDs: `STEP-001`, `STEP-002.001`, etc. |
| Step metadata | One fenced YAML metadata block per step. |
| Heading consistency | Heading ID/title must match YAML `id`/`title`. |
| Plan mutability | Immutable during execution. |
| Runtime state | Stored separately in `<automation_dir>/progress.json` (default `<automation_dir>` is `.wfrunner/automation`). |

## Step metadata contract

The source plan must include a non-empty project description. The compiler uses
that text as shared worker context and rejects plans whose compiled
`plan_description` is empty.

### Common step fields

| Field | Type | Required | Allowed values / notes |
|---|---:|---:|---|
| `schema_version` | integer | Yes | `1`. |
| `id` | string | Yes | `STEP-###` or `STEP-###.###`. |
| `title` | string | Yes | Non-empty. |
| `type` | string enum | Yes | `IMPLEMENTATION`, `HUMAN_GATE`, `ANALYSIS`. |

### `IMPLEMENTATION` step fields

| Field | Type | Required | Notes |
|---|---:|---:|---|
| `agent` | string | Yes | Worker agent persona (bring-your-own; WaterfallRunner ships `default.wfrunner` as the default). |
| `model` | string | Yes | `default` is valid. |
| `allowed_files` | string array | Yes | Repository-relative exact paths or folder patterns ending in `/*`. |
| `pre_analysis` | object | No | Optional diagnostic commands. |
| `verification` | object | Yes | Post-agent commands. |
| `retry` | object | Yes | Fix-attempt policy. |

The agent-facing task prose is authored as the step's Markdown body and lifted by the compiler into the compiled step's `prompt` string; there is no per-step prompt-template path. The compiler rejects `IMPLEMENTATION` steps with empty task prose. The orchestrator injects a per-type WaterfallRunner system prompt (`prompts/system_prompt.implementation.md` or `prompts/system_prompt.analysis.md`) on every invocation and assembles the worker message in code.

Forbidden on `IMPLEMENTATION`:

| Field | Reason |
|---|---|
| `depends_on` | Phase 1 uses strict sequential order. |
| `review` | Removed from Phase 1 YAML. |
| `risk` | Use explicit `HUMAN_GATE` instead. |
| `human_gate` | Human gates are separate steps. |

### `HUMAN_GATE` step fields

`HUMAN_GATE` steps have no additional required fields beyond the common step fields.

Optional on `HUMAN_GATE`:

| Field | Type | Required | Notes |
|---|---:|---:|---|
| `review_guidance` | string | No | Human-facing explanation of why the gate exists or what must be reviewed before approval. Never sent to a model. |
| `pre_analysis` | object | No | Optional diagnostic commands to run before stopping or auto-approving the gate. |

Forbidden on `HUMAN_GATE`:

| Field | Reason |
|---|---|
| `gate` | Structured gate metadata is not part of the Phase 1 contract. Use `review_guidance` for human-facing context. |
| `agent` | No agent is invoked. |
| `prompt` | No prompt is needed. |
| `model` | No model is used. |
| `allowed_files` | No files are changed. |
| `verification` | No verification is run. |
| `retry` | No retry is possible. |

### `ANALYSIS` step fields

Use `ANALYSIS` for diagnostic evidence generation and optional model-authored reports that must not modify Git-visible source files.

| Field | Type | Required | Notes |
|---|---:|---:|---|
| `artifact_files` | string array | Yes | Declared evidence or report files produced by the analysis step. |
| `pre_analysis` | object | No | Optional commands that generate evidence files. |
| `agent` | string | No | Optional agent for interpreting evidence and writing declared artifacts. If present, `model` is also required and the step's Markdown task prose must be non-empty. |
| `model` | string | No | Required when `agent` is present; `default` is valid. |

Command-only `ANALYSIS` steps may omit task prose when they also omit `agent`
and `model`; in that case no worker agent is invoked and the step is driven by
`pre_analysis` evidence generation.

Forbidden on `ANALYSIS`:

| Field | Reason |
|---|---|
| `allowed_files` | Analysis steps do not grant source-edit permission. |
| `verification` | Implementation verification is not part of the analysis step contract. |
| `retry` | Implementation retry is not part of the analysis step contract. |

## `pre_analysis` contract

| Field | Type | Required | Notes |
|---|---:|---:|---|
| `commands` | array | Yes | Ordered diagnostic commands. |

Each command has:

| Field | Type | Required | Notes |
|---|---:|---:|---|
| `id` | string | Yes | Stable identifier for filenames and reporting. |
| `run` | string | Yes | Shell command. |
| `purpose` | string | Yes | Human-readable reason. |
| `fail_on_nonzero` | boolean | Yes | Whether nonzero exit blocks the step. |
| `output_files` | string array | No | Declared files generated by the command for later human or agent reading. |

Output artifact contract:

| Artifact | Location |
|---|---|
| Full command log | `<automation_dir>/pre-analysis/<STEP_ID>/<COMMAND_ID>.log` |
| Summary metadata | `<automation_dir>/pre-analysis/<STEP_ID>/<COMMAND_ID>.summary.json` |

Summary metadata fields:

| Field | Type | Notes |
|---|---:|---|
| `step_id` | string | Step ID. |
| `command_id` | string | Pre-analysis command ID. |
| `command` | string | Command that ran. |
| `exit_code` | integer | Process exit code. |
| `status` | enum | `PASS`, `FAIL`, `ERROR`. |
| `duration_seconds` | number | Runtime. |
| `log_path` | string | Full log path. |
| `output_files` | array | Declared evidence files generated by the command, if any. |

Pre-analysis execution rules:

- `pre_analysis` may write runtime artifacts only under `<automation_dir>/`.
- When Git tracking is available, the orchestrator compares the Git-visible change set before and after `pre_analysis`.
- If that Git-visible change set differs, the orchestrator stops before agent invocation.
- Changes limited to ignored or otherwise Git-invisible paths do not count as `pre_analysis` tree modification.
- If Git tracking is unavailable, `pre_analysis` mutation tracking is disabled rather than using filesystem timestamp inspection.
- For `IMPLEMENTATION`, pre-analysis `FAIL` marks the step `FAILED` with failure reason code `PRE_ANALYSIS_FAILED`; pre-analysis `ERROR` marks the step `BLOCKED`.
- For `HUMAN_GATE`, pre-analysis runs before stopping or auto-approval. With `--approve-human-gates`, `PASS` marks the gate `DONE` and execution continues, `FAIL` marks it `FAILED`, and `ERROR` marks it `BLOCKED`.
- For `ANALYSIS`, pre-analysis may generate declared `output_files`. The step fails if pre-analysis or an optional analysis agent changes Git-visible source state.

## Verification contract

| Field | Type | Required | Notes |
|---|---:|---:|---|
| `commands` | string array | Yes | Commands run after agent execution. An empty list means no verification command execution is required for the step. |

Verification execution rules:

- If `commands` is empty, the orchestrator performs no verification command execution.
- If `commands` is non-empty, the orchestrator executes commands sequentially in listed order.
- Verification succeeds only if every command exits successfully.
- A well-formed nonzero exit is `FAIL`. A script execution problem, timeout, or unexpected runner exception is `ERROR`.
- Verification `FAIL` marks the step `FAILED` and may enter the retry loop. Verification `ERROR` marks the step `BLOCKED` and does not retry.

Verification output artifact contract:

| Artifact | Location |
|---|---|
| Full command log | `<automation_dir>/verification/<STEP_ID>/attempt-<N>-command-<M>.log` |
| Summary metadata | `<automation_dir>/verification/<STEP_ID>/attempt-<N>-command-<M>.summary.json` |

Verification summary fields:

| Field | Type | Notes |
|---|---:|---|
| `step_id` | string | Step ID. |
| `attempt` | integer | Implementation/fix attempt number. |
| `command_index` | integer | Position in verification command list. |
| `command` | string | Command that ran. |
| `exit_code` | integer | Process exit code. |
| `status` | enum | `PASS`, `FAIL`, `ERROR`. |
| `duration_seconds` | number | Runtime. |
| `stdout_tail` | string | Bounded output excerpt. |
| `stderr_tail` | string | Bounded error excerpt. |
| `log_path` | string | Full log path. |

## Retry contract

| Field | Type | Required | Notes |
|---|---:|---:|---|
| `max_fix_attempts` | integer | Yes | Recommended `0` or `1` in Phase 1. |

Retry input to the same step agent:

| Item | Required | Notes |
|---|---:|---|
| Step ID and title | Yes | Identifies target step. |
| Original allowed files | Yes | Same scope as original step. |
| Failed command | Yes | Command that failed. |
| Exit code | Yes | Objective failure signal. |
| Bounded stdout/stderr excerpt | Yes | Enough context without unbounded logs. |
| Full log path | Yes | Human/orchestrator reference. |
| Stop rules | Yes | Fix only the failure; stop if scope expands. |

The retry invocation uses the same agent and prompt template as the original implementation step. Verification failure details are passed as structured `failure_context`, not through a separate `fix-verification.md` prompt.

## Agent invocation contract

The orchestrator invokes Copilot CLI custom agents programmatically.

Required invocation information:

| Item | Notes |
|---|---|
| Agent name | From step `agent`. |
| Model | From step `model`; `default` resolves to `default_model` from config. |
| Prompt template | From step `prompt`. |
| Step ID | The only step the agent may execute. |
| Plan path | The required plan path supplied to the CLI. |
| Allowed files | Explicitly repeated in prompt. |
| Verification commands | Optional prompt context only; orchestrator owns verification and still reruns it independently. |
| Failure context | Included only for retry after verification `FAIL`. |

Agent result transport:

- The worker must return exactly one machine-readable JSON object.
- The orchestrator validates that object against a versioned agent-result JSON schema before accepting it.
- Missing JSON, malformed JSON, schema validation failure, or a mismatched `step_id` must stop execution and be recorded as an invalid agent result.
- A schema-valid `status: FAILED` must stop execution and mark the selected step `FAILED`; it is distinct from invalid JSON and from `BLOCKED`.
- A schema-valid `status: BLOCKED` must include `stop_condition_hit` and mark the selected step `BLOCKED`.
- Agent-claimed file lists and command lists are not part of the result contract. The orchestrator derives changed files from Git when tracking is available and owns verification execution.

Agent result contract:

| Field | Required | Notes |
|---|---:|---|
| `schema_version` | Yes | Integer. Must be `1`. |
| `step_id` | Yes | Must match requested step. |
| `status` | Yes | `DONE`, `FAILED`, or `BLOCKED`. |
| `notes` | No | Human-readable notes. |
| `stop_condition_hit` | No | Required if `status` is `BLOCKED`. |

## Orchestrator CLI contract

CLI commands:

| Command shape | Purpose |
|---|---|
| `wfrunner run <plan_path> [--config PATH]` | Prepare and run sequentially until completion or a stop condition. |
| `wfrunner run <plan_path> --prepare-only` | Validate and initialize runtime files without executing. |
| `wfrunner run <plan_path> --next-step-only` | Execute at most the next selected step. |
| `wfrunner run <plan_path> --resume` | Continue using existing progress. |
| `wfrunner run <plan_path> --reset` | Reset runtime progress for the plan. |
| `wfrunner run <plan_path> --reset-current-step` | Reset the current failed or in-progress step. |
| `wfrunner run <plan_path> --approve-human-gates` | Auto-approve `HUMAN_GATE` steps after optional pre-analysis passes. |
| `wfrunner validate <plan_path> [--config PATH]` | Validate plan structure and, when config is available, protected-path rules. |
| `wfrunner status <plan_path>` | Show progress status without requiring config. |
| `wfrunner init` | Write the starter `.wfrunner/wfrunner.toml` and prompts. |

Default behavior:

| Behavior | Default |
|---|---|
| Require clean working tree | Yes; a dirty start marks the selected `IMPLEMENTATION` step `BLOCKED` with `DIRTY_WORKTREE`. |
| Stop on human gate | Yes. |
| Stop on failure | Yes. |
| Scan ahead for other runnable steps | No. |
| Allow dirty start | No. |

## Progress file contract

Path:

| Setting | Value |
|---|---|
| Progress file | `<automation_dir>/progress.json` |
| Progress schema | `schemas/progress.schema.json` |

All `<automation_dir>` references use the configured `automation_dir` from `.wfrunner/wfrunner.toml` (default `.wfrunner/automation`).

The authoritative machine contract for the progress file is the JSON Schema at `schemas/progress.schema.json`.

Top-level required fields:

| Field | Type | Notes |
|---|---:|---|
| `schema_version` | integer | Must be `1`. |
| `plan_file` | string | Repository-relative plan path. |
| `last_run_id` | string | Run identifier in the form `RUN-YYYY-MM-DDTHH:MM:SSZ`. |
| `steps` | object | Per-step runtime state keyed by `STEP-###` or `STEP-###.###`. |

Required per-step fields:

| Field | Type | Notes |
|---|---:|---|
| `state` | enum | Runtime state. |
| `agent` | string/null | Agent used. |
| `model` | string/null | Model used. |
| `started_at` | string/null | RFC 3339 timestamp or `null`. |
| `completed_at` | string/null | RFC 3339 timestamp or `null`. |
| `pre_analysis` | object/null | Explicit pre-analysis summary object or `null`. |
| `verification` | object/null | Explicit verification summary object or `null`. |
| `fix_attempts` | integer | Number of fix attempts. |
| `commit` | string/null | Commit hash if committed. |
| `failure_reason` | object/null | Structured failure reason object or `null`. |

Nested summary objects:

| Field | Type | Notes |
|---|---:|---|
| `pre_analysis.status` | enum | `NOT_RUN`, `PASS`, `FAIL`, `ERROR`. |
| `pre_analysis.commands` | array | Ordered per-command summary references. |
| `verification.status` | enum | `NOT_RUN`, `PASS`, `FAIL`, `ERROR`. |
| `verification.attempts` | array | Ordered implementation or fix-attempt summaries. |
| `failure_reason.code` | enum | Machine-readable stop or failure code. |
| `failure_reason.message` | string | Human-readable explanation. |

Known failure reason codes include `AGENT_BLOCKED`, `INVALID_AGENT_RESULT`, `SCOPE_VIOLATION`, `PRE_ANALYSIS_FAILED`, `VERIFICATION_FAILED`, `VERIFICATION_TIMEOUT`, `HUMAN_GATE`, `DIRTY_WORKTREE`, `PLAN_VALIDATION_FAILED`, `MAX_STEPS_REACHED`, and `INVALID_PROGRESS_FILE`.

Validation rules:

- Additional properties are not allowed at the top level, per-step level, or within nested summary objects.
- `steps` keys must match `STEP-###` or `STEP-###.###`.
- `IN_PROGRESS` steps must have non-null `started_at`.
- `DONE`, `FAILED`, `BLOCKED`, and `SKIPPED` steps must have non-null `completed_at`.
- Progress files should be validated against `schemas/progress.schema.json` when loaded or resumed.

The implementation plan is immutable during execution.

For a `HUMAN_GATE`, approval is persisted in `.automation/progress.json` by setting the step runtime `state` to `DONE`. `completed_at` should record the approval time.

The implementation plan must not change while a run is active. If execution is stopped, including at a `HUMAN_GATE`, a human may update the plan manually. Any updated plan must pass automated validation before the next run or resume attempt.

## Run log contract

Path:

| Setting | Value |
|---|---|
| Run log | `<automation_dir>/run-log.md` |

Each entry should include:

| Section | Purpose |
|---|---|
| Timestamp and step ID | Identify event. |
| Agent | Worker used. |
| Pre-analysis summary | Diagnostic context if any. |
| Files changed | Git-derived changed file list. |
| Verification | Command status summary. |
| Retry | Whether retry occurred. |
| Commit | Commit hash if any. |
| Stop reason | Required for failed/blocked/gated steps. |

## Whole-plan report contract

Path:

| Setting | Value |
|---|---|
| Whole-plan report | `<automation_dir>/whole-plan-report.md` |

Report sections:

| Section | Purpose |
|---|---|
| Summary | Completed count and stop reason. |
| Completed steps | Step IDs and titles. |
| Stopped at | Current step and reason. |
| Verification summary | Pass/fail overview. |
| Files changed | Aggregated changed paths. |
| Commits | Commit hashes if any. |
| Human action required | Clear next action. |

## Patch snapshot contract

When a step fails after producing changes, WaterfallRunner should preserve recoverable evidence.

| Artifact | Location |
|---|---|
| Git diff patch | `<automation_dir>/patches/<STEP_ID>.diff` |

Patch snapshots are especially useful when verification or scope checks fail after the agent produced partially useful work.
