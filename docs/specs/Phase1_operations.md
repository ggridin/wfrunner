# Phase 1 Operations

## Short summary

This document describes how a human operator uses WaterfallRunner Phase 1 during normal development. It covers planning, validation, prepare/status checks, one-step execution, whole-plan execution, review, recovery, and rollback. It does not define new design decisions or implementation code.

## Operator assumptions

| Assumption | Phase 1 position |
|---|---|
| Execution location | Local developer machine. |
| Repository | Single Git repository. |
| Branch | Dedicated AI work branch, not `main`. |
| Agent | Copilot CLI custom agent. |
| Plan | Required plan path supplied to `wfrunner run`, `validate`, or `status`. |
| Runtime state | `<automation_dir>/` (default `.wfrunner/automation/`). |
| Human review | Required after whole-plan runs and at explicit gates unless gates were explicitly auto-approved. |

## Recommended branch discipline

Run WaterfallRunner on a dedicated branch.

Branch naming convention:

| Pattern | Purpose |
|---|---|
| `ai/phase1-run-YYYYMMDD` | Whole-plan or experimental AI run. |
| `ai/spec-update-YYYYMMDD` | Plan/schema/prompt updates. |

Do not run whole-plan automation directly on `main`.

## Daytime planning workflow

| Step | Action |
|---:|---|
| 1 | Create or revise the implementation plan file that will be passed to the CLI. |
| 2 | Keep steps small and sequential. |
| 3 | Use `IMPLEMENTATION` for source changes, `ANALYSIS` for source-preserving evidence generation, and `HUMAN_GATE` for review pauses. |
| 4 | List explicit `allowed_files` for every `IMPLEMENTATION` step, using exact paths or folder patterns ending in `/*`. |
| 5 | List explicit `artifact_files` for every `ANALYSIS` step. |
| 6 | Add `HUMAN_GATE` immediately before risky protected-file changes. |
| 7 | Define objective verification commands for implementation work. |
| 8 | Use `pre_analysis` only when diagnostic context is useful. |

## Validation workflow

Before running any step, validate the plan.

Expected validation outcomes:

| Outcome | Meaning |
|---|---|
| Pass | Plan is structurally valid and can be considered for execution. |
| Fail | Fix the plan before execution. |

Validation does not prove the plan is good. It only proves the plan follows the contract.

## Prepare and status workflow

Use prepare/status checks before real execution.

`wfrunner run <plan_path> --prepare-only` should confirm the plan validates and runtime files can be initialized. `wfrunner status <plan_path>` should show existing progress without requiring config, and should use the configured automation paths when config is available.

Before execution, confirm:

| Check | Expected answer |
|---|---|
| Which step would run next? | First incomplete step in file order. |
| Is the current step a gate? | If yes, execution would stop. |
| Which agent would run? | From step metadata. |
| Which files may change? | From `allowed_files`. |
| Which analysis artifacts may be generated? | From `artifact_files`. |
| Which pre-analysis commands would run? | From optional `pre_analysis`. |
| Which verification commands would run? | From `verification`. |

Prepare-only may create runtime files under `<automation_dir>/` but must not modify Git-visible project files.

## One-step execution workflow

Use one-step mode when testing the harness or running a small controlled change.

Expected lifecycle:

| Order | Action |
|---:|---|
| 1 | Validate plan. |
| 2 | Select first incomplete step. |
| 3 | Stop if selected step is `HUMAN_GATE`. |
| 4 | If selected step is `ANALYSIS`, run declared evidence generation and optional agent interpretation, then fail if Git-visible source state changes. |
| 5 | Require clean working tree before running the selected `IMPLEMENTATION` step; if dirty, mark it `BLOCKED` with `DIRTY_WORKTREE`. |
| 6 | Run optional pre-analysis. |
| 7 | If Git tracking is available, confirm pre-analysis did not introduce Git-visible changes. |
| 8 | Invoke agent. |
| 9 | Enforce `allowed_files`. |
| 10 | Run verification. |
| 11 | Retry once if allowed and needed. |
| 12 | Update progress and logs. |
| 13 | Commit if configured. |

## Whole-plan execution workflow

Use whole-plan mode only after prepare/status checks are sensible and the plan has been reviewed.

Recommended safeguards:

| Safeguard | Reason |
|---|---|
| Dedicated branch | Prevent unintended changes to `main`. |
| Clean working tree | Avoid mixing human and agent changes; dirty start blocks the selected implementation step. |
| Stop on failure | Avoid cascading bad changes. |
| Stop on human gate | Preserve human approval. |
| Commit per step | Every successful implementation step is committed automatically, creating rollback points. |

The whole-plan run should stop on:

- Plan validation failure.
- Dirty working tree before the selected `IMPLEMENTATION` step starts; mark the step `BLOCKED` with `DIRTY_WORKTREE`.
- `HUMAN_GATE`.
- `HUMAN_GATE` pre-analysis `FAIL` or `ERROR` when gates are auto-approved.
- Agent failure or block.
- `allowed_files` violation.
- Verification failure after allowed retry.
- Protected-file violation.
- Command timeout.
- Completion of all steps.

## Review workflow

After a whole-plan run, review:

| Artifact | Purpose |
|---|---|
| `<automation_dir>/whole-plan-report.md` | Summary and next action. |
| `<automation_dir>/run-log.md` | Detailed execution history. |
| `<automation_dir>/progress.json` | Machine-readable state. |
| `<automation_dir>/verification/` | Full command logs. |
| `<automation_dir>/pre-analysis/` | Diagnostic context logs. |
| `<automation_dir>/patches/` | Recoverable diffs for failed work. |
| Git commits | Step checkpoints. |
| Git diff | Actual repository changes. |

All `<automation_dir>` paths use the configured `automation_dir` from `.wfrunner/wfrunner.toml` (default `.wfrunner/automation/`).

Review decisions:

| Decision | When to choose |
|---|---|
| Accept progress | Steps are correct and verified. |
| Revise plan | Plan ambiguity or missing scope was discovered. |
| Approve gate | Human gate is acceptable. |
| Reject gate | Next risky step should not proceed. |
| Add follow-up step | Work is useful but incomplete. |
| Roll back | Committed work should be discarded. |
| Stop experiment | Harness behavior is not trustworthy enough yet. |

## Human gate handling

When WaterfallRunner stops at a `HUMAN_GATE`, the human should:

| Action | Purpose |
|---|---|
| Review the gate `description` and gated change context | Understand why approval is needed. |
| Review relevant prior steps | Check the basis for the decision. |
| Approve continuation | Allow the next run to proceed past the gate. |
| Optionally revise the plan manually while the run is stopped | Clarify scope or adjust the next work before rerunning. |
| Revalidate the updated plan | Ensure the next run still satisfies the contract. |
| Update `<automation_dir>/progress.json` according to recovery rules | Make the next run deterministic. |

Gate approval must be persisted in `<automation_dir>/progress.json`. The implementation plan must not change while a run is active, but a human may update it manually after execution stops, including at a `HUMAN_GATE`. Any updated plan must pass automated validation before the next run or resume attempt.

For unattended runs where gates have been reviewed in advance, `wfrunner run <plan_path> --approve-human-gates` marks a gate `DONE` and continues only after optional gate pre-analysis passes. Gate pre-analysis `FAIL` marks the gate `FAILED`; `ERROR` marks it `BLOCKED`.

## Recovery workflow

Common recovery cases:

| Case | Recommended response |
|---|---|
| Plan validation fails | Fix plan manually; rerun validation before resuming. |
| Agent blocks on ambiguity | Clarify the step or split it. |
| Agent changes unlisted file | Inspect diff; update plan only if change is legitimate. |
| Verification fails | Review logs; revise step or add follow-up step. |
| Protected-file rule blocks | Insert or approve an explicit `HUMAN_GATE`. |
| Runtime progress is inconsistent | Stop and manually inspect `<automation_dir>/progress.json` and Git state. |

## Rollback workflow

If successful steps were committed independently, rollback should be Git-based.

Recommended approach:

| Situation | Response |
|---|---|
| Last committed step is bad | Revert or reset according to normal Git practice. |
| Multiple committed steps are bad | Revert the relevant step commits in order. |
| Failed uncommitted work remains | Use patch snapshot if useful, then restore working tree. |
| Plan needs redesign | Update implementation plan before rerunning. |

## Release readiness checklist

Before declaring Phase 1 complete, record deterministic validation evidence and one real-adapter smoke check.

Required deterministic checks:

```powershell
python -m tools.wfrunner validate docs\implementation-plan.md
python -m tools.wfrunner validate docs\implementation_9.md
python -m pytest tests -q
git status --short
```

Required packaged executable smoke checks use the freshly built canonical artifact at `dist\wfrunner.exe`:

```powershell
python build.py
dist\wfrunner.exe --version
dist\wfrunner.exe --help
dist\wfrunner.exe run --help
dist\wfrunner.exe validate docs\implementation-plan.md
dist\wfrunner.exe status docs\implementation-plan.md
```

Run `dist\wfrunner.exe init` from a disposable Git repository and expect exit code `0` with `.wfrunner\wfrunner.toml`, `.wfrunner\prompts\implement-step.md`, `.github\agents\spec-implementer.agent.md`, and WaterfallRunner `.gitignore` entries created. Missing bundled runtime resources should return exit code `2` with a packaging diagnostic rather than a raw file-loading traceback.

Phase 1 uses PyInstaller's default `runtime_tmpdir` (system temp) for the Windows single-file executable. Extracting into the current directory (`runtime_tmpdir="."`) unpacks a transient `_MEIxxxxxx/` directory into the working directory, which pollutes a target repository's Git worktree and breaks clean-tree detection (blocking IMPLEMENTATION steps) — so the executable is safe to run from any directory, including a copy at a target repository root. Release validation must smoke-check the canonical `dist\wfrunner.exe` artifact.

The `git status --short` output must not show `?? schemas/`; runtime schema contracts under `schemas/` must be intentional source files. Generated runtime files under the configured `<automation_dir>/` remain local artifacts.

Required real Copilot CLI smoke check:

1. Confirm `copilot` is installed and authenticated for the local environment.
2. Create or choose a minimal one-step plan on a disposable branch with one harmless `allowed_files` target and a fast verification command.
3. Run `wfrunner run <plan_path> --next-step-only` using the real `CopilotCliAdapter`, not `FakeAgentAdapter`.
4. Confirm the agent returns exactly one schema-valid agent-result JSON object.
5. Confirm the run writes `<automation_dir>/progress.json`, `<automation_dir>/run-log.md`, `<automation_dir>/whole-plan-report.md`, and an agent log under `<automation_dir>/agent-logs/`.
6. Confirm the selected step either completes with verification evidence or stops with a schema-valid `FAILED`/`BLOCKED` result and a clear failure reason.

If the smoke check cannot be run in the release environment, release notes must state that readiness is limited to deterministic fake-agent coverage and schema/CLI validation.

## Operational caution

WaterfallRunner should remain intentionally boring in Phase 1.

Avoid adding operational complexity until the basic local loop is reliable:

- No parallel runs.
- No remote execution.
- No implicit approval without the explicit `--approve-human-gates` flag.
- No automatic merge.
- No uncontrolled retries.
- No broad file globs.
- No hidden dependency scheduler.
