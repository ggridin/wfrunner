# Phase 1 Test Scenarios

## Short summary

TDD is practical for the deterministic parts of WaterfallRunner: schema validation, plan parsing, step selection, file allowlist enforcement, protected-file gate rules, pre-analysis execution, verification execution, progress writing, report generation, and fake-agent orchestration.

TDD is not directly reliable for real Copilot model output because model behavior is nondeterministic. Instead, Phase 1 tests should use a fake agent adapter with deterministic outputs.

## Testing scope

| Component | TDD suitability | Notes |
|---|---:|---|
| Plan parser | High | Deterministic file parsing. |
| JSON Schema validation | High | Deterministic metadata validation. |
| Workflow validation | High | Deterministic rules. |
| Step selection | High | Strict document order. |
| `allowed_files` enforcement | High | Deterministic Git status comparison. |
| Protected-file gate validation | High | Deterministic path and prior-step rules. |
| Pre-analysis runner | High | Can use fake commands. |
| Verification runner | High | Can use fake commands. |
| Retry control | High | Can use fake failing/passing commands. |
| Progress/log/report output | High | Deterministic file output. |
| Real Copilot output | Low | Use fake agent adapter for tests. |

## Test scenario contract

Each test scenario should specify:

| Field | Purpose |
|---|---|
| Scenario ID | Stable test identifier. |
| Purpose | What rule is being tested. |
| Initial plan | Relevant step metadata shape. |
| Initial progress | Existing runtime state, if any. |
| Initial Git state | Clean, dirty, changed files, etc. |
| Fake agent behavior | What files are changed and what result is returned. |
| Command behavior | Pre-analysis/verification command exit codes and outputs. |
| Expected orchestrator decision | Continue, stop, fail, block, commit, etc. |
| Expected artifacts | Progress, logs, reports, patches. |

## Validation scenarios

| ID | Scenario | Expected result |
|---|---|---|
| VAL-001 | Valid minimal `IMPLEMENTATION` step | Plan passes validation. |
| VAL-002 | Valid minimal `HUMAN_GATE` step | Plan passes validation. |
| VAL-003 | Missing YAML metadata block | Validation fails. |
| VAL-004 | Malformed YAML | Validation fails with actionable error. |
| VAL-005 | Unknown field in step metadata | Validation fails. |
| VAL-006 | Duplicate step ID | Validation fails. |
| VAL-007 | Non-contiguous step IDs | Validation fails. |
| VAL-008 | Step IDs out of order | Validation fails. |
| VAL-009 | Heading ID differs from YAML ID | Validation fails. |
| VAL-010 | Heading title differs from YAML title | Validation fails. |
| VAL-011 | `IMPLEMENTATION` missing `allowed_files` | Validation fails. |
| VAL-012 | Step includes removed `state` field | Validation fails. |
| VAL-013 | Step includes removed `depends_on` field | Validation fails. |
| VAL-014 | Step includes removed `review` field | Validation fails. |
| VAL-015 | Step includes removed `risk` field | Validation fails. |
| VAL-016 | Step includes removed `human_gate` field | Validation fails. |
| VAL-017 | Valid minor step sequence such as `STEP-002`, `STEP-002.001`, `STEP-002.002` | Plan passes validation. |
| VAL-018 | Minor steps have a gap or appear before their parent major step | Validation fails. |
| VAL-019 | `HUMAN_GATE` includes optional `pre_analysis` | Plan passes validation. |

## Protected-file scenarios

| ID | Scenario | Expected result |
|---|---|---|
| PROT-001 | Step modifies `tools/run_plan.py` without prior `HUMAN_GATE` | Validation or orchestration blocks. |
| PROT-002 | Step modifies `schemas/` after immediately preceding `HUMAN_GATE` | Allowed by validation. |
| PROT-003 | Step modifies `.github/agents/` without prior `HUMAN_GATE` | Validation or orchestration blocks. |
| PROT-004 | Prior human gate exists but is not immediately before protected change | Validation fails. |

## Step-selection scenarios

| ID | Scenario | Expected result |
|---|---|---|
| SEL-001 | Empty progress, first step is `IMPLEMENTATION` | Select `STEP-001`. |
| SEL-002 | Progress marks `STEP-001` done and has no entry for `STEP-002` | Select `STEP-002`. |
| SEL-003 | First incomplete step is `HUMAN_GATE` | Stop at gate. |
| SEL-004 | Progress marks the first incomplete step `BLOCKED` | Stop. |
| SEL-005 | Progress marks the current step `FAILED` and a later step is otherwise runnable | Do not scan ahead; stop. |
| SEL-006 | Step marked `SKIPPED` by human state | Continue to next step. |
| SEL-007 | Progress includes minor step IDs | Select in document order, with parent major before its minor steps. |

## Execution preflight scenarios

| ID | Scenario | Expected result |
|---|---|---|
| PREF-001 | Selected `IMPLEMENTATION` step starts with dirty working tree | Mark the selected step `BLOCKED` with `DIRTY_WORKTREE` and stop before `pre_analysis` or agent invocation. |

## Pre-analysis scenarios

| ID | Scenario | Expected result |
|---|---|---|
| PRE-001 | No `pre_analysis` property | Proceed to agent invocation. |
| PRE-002 | Pre-analysis command exits zero | Save output and proceed. |
| PRE-003 | Pre-analysis command exits nonzero with `fail_on_nonzero: true` | Stop before agent invocation. |
| PRE-004 | Pre-analysis command exits nonzero with `fail_on_nonzero: false` | Save output and proceed. |
| PRE-005 | Pre-analysis introduces Git-visible changes | Stop before agent invocation. |
| PRE-006 | Pre-analysis changes only ignored or Git-invisible files | Save output and proceed. |
| PRE-007 | Git tracking is unavailable during pre-analysis | Do not fail solely on mutation detection. |
| PRE-008 | Pre-analysis output is produced | Store full log without passing output to the agent prompt. |
| PRE-009 | Pre-analysis runner cannot execute command or times out | Mark selected implementation step `BLOCKED`. |
| PRE-010 | `HUMAN_GATE` pre-analysis exits zero | Record pre-analysis and stop at gate unless auto-approval is enabled. |
| PRE-011 | `HUMAN_GATE` pre-analysis exits nonzero | Mark gate `FAILED`. |
| PRE-012 | `HUMAN_GATE` pre-analysis errors or times out | Mark gate `BLOCKED`. |

## Agent invocation scenarios

| ID | Scenario | Expected result |
|---|---|---|
| AGENT-001 | Fake agent returns schema-valid result with `status: DONE` and modifies allowed file | Proceed to verification. |
| AGENT-002 | Fake agent returns schema-valid result with `status: BLOCKED` and `stop_condition_hit` | Stop and record block reason. |
| AGENT-003 | Fake agent returns malformed JSON or schema-invalid result | Stop and record invalid agent result. |
| AGENT-004 | Fake agent returns result with mismatched `step_id` | Stop and record invalid agent result. |
| AGENT-005 | Agent modifies no files when step expected changes | Verification decides outcome. |
| AGENT-006 | Fake agent returns `status: BLOCKED` without `stop_condition_hit` | Stop and record invalid agent result. |
| AGENT-007 | Copilot exits zero without returning an agent-result JSON object | Stop and record invalid agent result. |
| AGENT-008 | Fake agent returns schema-valid `status: FAILED` | Stop and mark selected step `FAILED` without verification. |

## `allowed_files` scenarios

| ID | Scenario | Expected result |
|---|---|---|
| ALLOW-001 | Existing allowed file modified | Allowed. |
| ALLOW-002 | Listed non-existing file created | Allowed. |
| ALLOW-003 | Unlisted file modified | Stop and record scope violation. |
| ALLOW-004 | Unlisted file created | Stop and record scope violation. |
| ALLOW-005 | Listed file deleted | Allowed. |
| ALLOW-006 | File renamed where both source and destination are in `allowed_files` | Allowed. Source detected as `deleted`, destination as `renamed`. |
| ALLOW-007 | File renamed where only destination is in `allowed_files` | Stop and record scope violation for the source path. |
| ALLOW-008 | Folder pattern ending in `/*` matches a changed nested file | Allowed. |

## Verification scenarios

| ID | Scenario | Expected result |
|---|---|---|
| VER-001 | Single verification command exits zero | Step can complete. |
| VER-002 | First verification command fails | Stop or retry depending on policy. |
| VER-003 | Multiple commands, later command fails | Treat verification as failed. |
| VER-004 | Verification command times out or cannot execute | Treat verification as `ERROR`, mark step `BLOCKED`, and do not retry. |
| VER-005 | Verification output is large | Store full log and report bounded excerpt. |
| VER-006 | `verification.commands` is empty | Step can complete after scope check without verification command execution. |

## Retry scenarios

| ID | Scenario | Expected result |
|---|---|---|
| RETRY-001 | Verification fails and `max_fix_attempts` is `0` | Stop without retry invocation. |
| RETRY-002 | Verification fails and one retry is allowed | Invoke the same step agent once with `failure_context`. |
| RETRY-003 | Retry modifies only allowed files and verification passes | Step completes. |
| RETRY-004 | Retry modifies unlisted file | Stop with scope violation. |
| RETRY-005 | Verification still fails after retry | Stop and mark failed. |
| RETRY-006 | Retry agent reports requirement ambiguity | Stop and mark blocked. |

## Progress/log/report scenarios

| ID | Scenario | Expected result |
|---|---|---|
| ART-001 | Successful step | Progress marks step done and conforms to the progress schema. |
| ART-002 | Successful step with commit enabled | Progress records commit hash. |
| ART-003 | Failed verification | Progress records structured failure reason and verification summary path. |
| ART-004 | Scope violation after agent run | Patch snapshot is saved. |
| ART-005 | Human gate reached | Whole-plan report names gate and required human action. |
| ART-006 | Human gate auto-approved | Whole-plan report records the approved gate and subsequent progress. |
| ART-007 | Resume loads malformed `.automation/progress.json` | Stop and report invalid progress file. |

## End-to-end scenarios

| ID | Scenario | Expected result |
|---|---|---|
| E2E-001 | One valid implementation step passes verification | Step completes and report is written. |
| E2E-002 | Two implementation steps pass sequentially | Both complete in order. |
| E2E-003 | Step 1 passes, step 2 is human gate | Run stops at step 2. |
| E2E-004 | Step 1 fails verification | Run stops; step 2 is not attempted. |
| E2E-005 | Next-step-only mode with two runnable steps | Only first eligible step runs. |
| E2E-006 | Selected implementation step starts dirty | Run stops with the selected step recorded as `BLOCKED`. |
| E2E-007 | Whole-plan mode with a gate and `--approve-human-gates` | Steps before and after the gate run in order after gate approval. |

## Configuration scenarios

| ID | Scenario | Expected result |
|---|---|---|
| CONFIG-001 | `wfrunner run` has no config file and no `--config` | Run exits with a clear configuration error. |
| CONFIG-002 | Config file has valid top-level keys | `WaterfallRunnerConfig` populated with provided values. |
| CONFIG-003 | Config file has unknown top-level key | Config loads; unknown keys are ignored or produce a warning. |
| CONFIG-004 | Config file has `[copilot_cli]` section with custom `timeout_seconds` | `CopilotCliConfig.timeout_seconds` reflects the configured value. |
| CONFIG-005 | Config file has `[copilot_cli]` section with custom `allow_tools` and `deny_tools` | `CopilotCliConfig` tool lists reflect the configured values. |
| CONFIG-006 | Config file has `[protected_paths]` section with custom `paths` | `WaterfallRunnerConfig.protected_paths` contains the built-in floor plus configured paths. |
| CONFIG-007 | Config file has `[git]` section with `push_required = false` | `GitConfig.push_required` is `false`; orchestrator skips `git push`. |
| CONFIG-008 | Config file has invalid TOML syntax | Config load fails with actionable error. |
| CONFIG-009 | Config file has invalid type for a known key | Config load fails with an actionable error. |
| CONFIG-010 | Config file `automation_dir` is a custom path | All runtime artifacts written under the custom path. |
| CONFIG-011 | Orchestrator completes a successful `IMPLEMENTATION` step | The step's changes are committed automatically. |
| CONFIG-012 | Config file omits `[protected_paths]` | Effective protected-path list still contains the built-in floor. |
| CONFIG-014 | Config file sets `[protected_paths].paths = []` | Effective protected-path list still contains the built-in floor. |
| CONFIG-013 | Config file sets git and pre-analysis timeouts | Orchestrator uses configured timeout values. |

## Rename detection scenarios

| ID | Scenario | Expected result |
|---|---|---|
| RENAME-001 | `GitChangeDetector` processes a Git rename (`R` status) | Source emitted as `deleted`, destination emitted as `renamed`. |
| RENAME-002 | Rename destination is in `allowed_files` but source is not | `check_allowed_files` reports scope violation for source. |
| RENAME-003 | Both rename source and destination are in `allowed_files` | `check_allowed_files` allows the rename. |
