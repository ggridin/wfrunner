# Phase 1 Architecture

## Short summary

Phase 1 is the smallest useful local proof of concept for WaterfallRunner.

It validates a structured implementation plan, runs the first incomplete step in strict document order, invokes a Copilot CLI custom agent for that one step, enforces `allowed_files`, runs verification commands, optionally performs focused retry, records progress, and stops at failure, completion, or `HUMAN_GATE` unless gates are explicitly auto-approved.

## Phase 1 goal

Prove that a local deterministic controller can turn a validated implementation plan into controlled AI-assisted implementation without building a new coding agent.

The core loop is:

| Stage | Responsibility |
|---|---|
| Validate plan | Reject malformed or unsafe step metadata before execution. |
| Select next step | Use strict Markdown document order and block a selected `IMPLEMENTATION` step if it starts with a dirty worktree. |
| Run optional pre-analysis | Collect bounded diagnostic context before the agent runs without introducing new Git-visible repository changes when Git is available. |
| Invoke agent | Ask Copilot CLI to execute exactly one step. |
| Enforce scope | Reject changes outside `allowed_files`. |
| Verify | Run objective verification commands. |
| Retry if allowed | Feed structured failure context to the same step agent. |
| Commit and log | Save progress, logs, reports, and optional Git commit. |
| Stop safely | Stop on human gate, failure, block, or completion. |

## Phase 1 non-goals

- No parallel execution.
- No dependency graph scheduler.
- No `depends_on` field.
- No built-in AI code-review gate.
- No `risk` metadata.
- No `DOCUMENTATION` step type.
- No cloud execution.
- No multi-repository orchestration.
- No remote sandbox.
- No automatic merge to `main`.
- No complex workflow framework.

## Execution model

Phase 1 uses strict sequential execution.

The implementation plan is treated as an ordered script. The orchestrator selects the first step in file order whose runtime state is not complete. It does not scan ahead for another runnable step.

This means:

- Each step implicitly depends on all prior non-skipped steps.
- If the current step is blocked, failed, or waiting for human approval, execution stops.
- If a selected `IMPLEMENTATION` step starts with a dirty worktree, the orchestrator blocks that step instead of trying to separate pre-existing edits from later changes.
- Step IDs must be ordered and contiguous.
- The document order is the dependency model.

## Step types

Phase 1 supports only two step types:

| Type | Meaning |
|---|---|
| `IMPLEMENTATION` | Agent-executed task that may change only paths matched by `allowed_files`. |
| `HUMAN_GATE` | Human approval point. The orchestrator stops and does not invoke an agent. |

Documentation updates, schema updates, tests, scripts, prompt changes, and configuration changes are all modeled as `IMPLEMENTATION` steps. If the work is risky, place a `HUMAN_GATE` immediately before it.

## Human gates

A `HUMAN_GATE` is a real workflow step, not a Boolean property on other steps.

The orchestrator behavior is:

| Condition | Behavior |
|---|---|
| Current step is `HUMAN_GATE` | Stop unless `--approve-human-gates` is set and optional pre-analysis passes. |
| Human gate approved later | Human may manually revise the plan while the run is stopped, validates the updated plan if changed, updates `.automation/progress.json` according to the recovery rules, then reruns. |
| Human does not approve | Human leaves the run stopped or manually revises the plan before a later validated rerun. |

## Scope control

Every `IMPLEMENTATION` step must declare `allowed_files`.

`allowed_files` is a strict allowlist of repository-relative paths that the step may change. Exact file paths allow matching created, modified, deleted, or renamed paths. Folder patterns ending in `/*` allow files under that prefix, including nested files. Renames pass only when both the source path and destination path match `allowed_files`; Git rename detection emits the source as `deleted` and the destination as `renamed`.

## Verification model

Verification is orchestrator-owned.

The agent may run tests while working, but WaterfallRunner still reruns the configured verification commands and treats command exit codes as authoritative.

If verification returns `FAIL` and the step allows retry, WaterfallRunner feeds structured failure context to the same step agent and prompt. WaterfallRunner then reruns verification. Verification `ERROR` blocks the step without retry. The agent's claim of success is not trusted without orchestrator verification.

## Configuration

WaterfallRunner reads runtime configuration from `.wfrunner/wfrunner.toml`. This file is Git-ignored and user-local. It controls settings such as the default model, automation directory, Copilot CLI tool permissions and timeout, protected paths, Git timeouts, pre-analysis timeout, and Git commit/push behavior.

`wfrunner run` requires a config file, either through `--config` or the default `.wfrunner/wfrunner.toml`. `wfrunner validate` can run without config, but then it skips protected-path validation. The file uses top-level keys and optional TOML sections (`[copilot_cli]`, `[protected_paths]`, `[git]`).

## Runtime state

The implementation plan describes intended work and remains immutable during execution. Runtime state, including `HUMAN_GATE` approval, is kept separately under the configured `automation_dir` (default `.wfrunner/automation/`).

This avoids turning the plan into a noisy execution log and keeps the plan reviewable.

## Protected files

The init template protects the following areas because they affect WaterfallRunner's own guardrails:

| Protected area | Reason |
|---|---|
| `schemas/` | Defines metadata contract. |
| `tools/validate_plan.py` | Enforces plan correctness. |
| `tools/run_plan.py` | Owns orchestration and safety behavior. |
| `.github/agents/` | Defines worker-agent behavior. |
| `.github/copilot-instructions.md` | Influences Copilot behavior. |
| `prompts/` | Defines reusable prompt contracts. |
| `.wfrunner/wfrunner.toml` | Controls runtime configuration. |

Protected paths have a non-removable built-in floor covering WaterfallRunner guardrails. The `[protected_paths]` section in `.wfrunner/wfrunner.toml` adds project-specific protected paths; omitting the section or setting `paths = []` does not remove the built-in floor. The orchestrator enforces the effective protected-path list regardless of agent or skill configuration.

A step that changes protected files should be preceded by a `HUMAN_GATE`.

## Phase 1 success criteria

Phase 1 succeeds if:

- A plan with valid metadata passes validation.
- Invalid metadata fails validation with useful errors.
- Steps execute strictly in document order.
- `HUMAN_GATE` stops execution unless explicitly auto-approved after optional pre-analysis passes.
- Copilot is invoked for exactly one step at a time.
- Changes outside `allowed_files` are detected and rejected.
- Verification commands are run and logged by the orchestrator.
- A focused retry can be attempted after verification failure when configured.
- Progress, logs, and a whole-plan report are produced.
- Successful steps can be committed independently.
