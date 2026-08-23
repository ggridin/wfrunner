# WaterfallRunner Decision Log

## Short summary

This file records the current architectural decisions for WaterfallRunner and Phase 1. It is intentionally concise. The goal is to preserve the reasoning behind guardrail choices without repeating the full design.

## ADR-001 — WaterfallRunner is a controller, not a coding agent

| Field | Decision |
|---|---|
| Status | Accepted |
| Scope | Project-wide |

WaterfallRunner will not implement its own coding model or coding agent. It will orchestrate existing agents, starting with GitHub Copilot CLI custom agents.

Rationale:

- Coding agents are evolving quickly.
- The durable value is in workflow discipline, validation, gates, verification, and auditability.
- A thin deterministic controller is easier to build and maintain.

Consequences:

- WaterfallRunner should keep worker-agent integration replaceable.
- Model-specific behavior should be isolated behind invocation contracts.

## ADR-002 — Phase 1 uses strict sequential execution

| Field | Decision |
|---|---|
| Status | Accepted |
| Scope | Phase 1 |

Phase 1 executes steps in Markdown file order. It does not scan ahead for another runnable step.

Rationale:

- Sequential execution is easier to understand and audit.
- Human gates are stronger when the orchestrator cannot skip around them.
- Git history is cleaner when each step becomes a checkpoint.

Consequences:

- No dependency scheduler is needed in Phase 1.
- File order is the dependency model.

## ADR-003 — Remove `depends_on` from Phase 1 YAML

| Field | Decision |
|---|---|
| Status | Accepted |
| Scope | Phase 1 |

Phase 1 does not use `depends_on`.

Rationale:

- In strict sequential mode, every step implicitly depends on all previous non-skipped steps.
- A separate dependency field creates a second model that can contradict document order.

Consequences:

- Step IDs must be ordered and contiguous.
- Future graph scheduling would require a later design change.

## ADR-004 — Use only `IMPLEMENTATION` and `HUMAN_GATE` step types

| Field | Decision |
|---|---|
| Status | Accepted |
| Scope | Phase 1 |

Phase 1 supports only two step types.

Rationale:

- A step type should exist only when orchestrator behavior differs.
- Documentation changes behave like implementation steps with documentation files in `allowed_files`.
- Code review and review-fixing are not core Phase 1 step types.

Consequences:

- `DOCUMENTATION`, `CODEREVIEW`, and `FIX_REVIEW_FINDINGS` are removed from Phase 1.

## ADR-005 — Human gates are explicit steps

| Field | Decision |
|---|---|
| Status | Accepted |
| Scope | Phase 1 |

Human approval is represented by `type: HUMAN_GATE`, not by `human_gate.required` on other steps.

Rationale:

- An explicit gate is easier to see in the plan.
- Sequential execution guarantees the gate cannot be skipped.
- The schema is simpler.

Consequences:

- `human_gate.required` is removed.
- Risky operations should be preceded by a `HUMAN_GATE` step.
- `HUMAN_GATE` may include an optional human-facing `description` and optional `pre_analysis`.
- The implementation plan remains immutable while a run is active.
- If execution is stopped, including at a `HUMAN_GATE`, the plan may be updated manually and must pass validation before the next run.
- Human approval is persisted in `.automation/progress.json`.

## ADR-006 — Remove `review` from Phase 1 step YAML

| Field | Decision |
|---|---|
| Status | Accepted |
| Scope | Phase 1 |

AI code review is not part of the Phase 1 step contract.

Rationale:

- AI review is subjective and model-dependent.
- Verification commands are more objective.
- Review workflows can be added later after the base loop is stable.

Consequences:

- No `review` field in Phase 1 YAML.
- Manual review happens during morning review.
- Future AI review can be added as a separate operation or later phase.

## ADR-007 — Remove `risk` from Phase 1 step YAML

| Field | Decision |
|---|---|
| Status | Accepted |
| Scope | Phase 1 |

Phase 1 does not use `risk` metadata.

Rationale:

- Risk is better represented directly by explicit `HUMAN_GATE` steps.
- Fewer metadata fields reduce schema ambiguity.
- Human approval remains visible in the ordered plan.

Consequences:

- No `risk` field in the step schema.
- Protected-file changes should require an immediately preceding `HUMAN_GATE`.

## ADR-008 — Keep `allowed_files`

| Field | Decision |
|---|---|
| Status | Accepted |
| Scope | Phase 1 |

Every `IMPLEMENTATION` step must declare `allowed_files`.

Rationale:

- File allowlisting is one of the strongest practical guardrails against agent drift.
- New file creation can still be supported by listing the intended path before execution.

Consequences:

- Unlisted created or modified files cause failure/blockage.
- Listed deletions are allowed; unlisted deletions cause a scope violation.
- Folder patterns ending in `/*` allow files under that repository-relative prefix.
- Renames are allowed only when both the source and destination match `allowed_files`.

## ADR-009 — Verification is orchestrator-owned

| Field | Decision |
|---|---|
| Status | Accepted |
| Scope | Phase 1 |

WaterfallRunner runs verification commands after agent execution and treats exit codes as authoritative.

Rationale:

- Agent claims of success are not enough.
- The orchestrator must own the pass/fail decision.
- Command logs create evidence for morning review.

Consequences:

- Agents may run tests while working, but WaterfallRunner reruns verification.
- Verification output can feed retry only through structured orchestrator-owned failure context.
- The worker-agent result should use a versioned JSON schema validated by the orchestrator.
- Agent-claimed file lists and command lists are not part of the control contract.

## ADR-010 — Add optional `pre_analysis`

| Field | Decision |
|---|---|
| Status | Accepted |
| Scope | Phase 1 |

Phase 1 supports optional `pre_analysis` for read-only diagnostic commands before agent invocation.

Rationale:

- Some tasks benefit from coverage, static analysis, performance baseline, or existing report context.
- The orchestrator should collect and bound this context rather than letting the agent improvise it.

Consequences:

- Pre-analysis must not modify the working tree.
- Full output is logged. Pre-analysis output is not passed to the agent prompt.
- Pre-analysis does not replace verification.

## ADR-011 — TDD targets deterministic WaterfallRunner behavior

| Field | Decision |
|---|---|
| Status | Accepted |
| Scope | Phase 1 |

TDD should focus on deterministic validator and orchestrator behavior, not real model output.

Rationale:

- Schema validation, step selection, allowlist enforcement, progress writing, and verification running are deterministic.
- Real Copilot responses are nondeterministic and should not be unit-test dependencies.

Consequences:

- Use a fake agent adapter for orchestrator tests.
- Test contracts and state transitions rather than model quality.

## ADR-012 — Do not create code snippets document yet

| Field | Decision |
|---|---|
| Status | Accepted |
| Scope | Documentation pack |

`Phase1_code_snippets.md` will not be created until design and API contracts are complete.

Rationale:

- Code snippets should emerge during implementation planning.
- Premature snippets can become stale or constrain the design too early.

Consequences:

- Current documentation remains architectural, design, contract, test, operation, and decision focused.

## ADR-013 — Migrate runtime configuration from pyproject.toml to .wfrunner/wfrunner.toml

| Field | Decision |
|---|---|
| Status | Accepted |
| Scope | Phase 5 |

Runtime configuration moves from `[tool.wfrunner]` in `pyproject.toml` to `.wfrunner/wfrunner.toml`. The TOML file uses top-level keys without the `[tool.wfrunner]` nesting.

Rationale:

- `pyproject.toml` should contain only build-system and project metadata, not per-user runtime settings.
- `.wfrunner/wfrunner.toml` is Git-ignored, making it suitable for user-local preferences.
- Separating runtime config from build metadata simplifies packaging.

Consequences:

- `.wfrunner/` directory is Git-ignored.
- `load_config()` reads `.wfrunner/wfrunner.toml` instead of `pyproject.toml`.
- The `[tool.wfrunner]` section is removed from `pyproject.toml`.
- `.wfrunner/wfrunner.toml` is itself a protected file.

## ADR-014 — Protected paths use a built-in floor plus wfrunner.toml additions

| Field | Decision |
|---|---|
| Status | Accepted |
| Scope | Phase 5 |

Protected paths use a non-removable built-in floor for WaterfallRunner guardrails. The `[protected_paths]` section in `.wfrunner/wfrunner.toml` adds project-specific protected paths, and the orchestrator enforces the union at runtime.

Rationale:

- Different projects may need additional protected paths.
- WaterfallRunner guardrail files should remain protected even when a project omits `[protected_paths]` or sets `paths = []`.
- Adding `.wfrunner/wfrunner.toml` itself as a protected file keeps runtime configuration changes behind a human gate.

Consequences:

- `plan_validator.py` and `scope_enforcer.py` receive the effective protected-path list from config loading.
- The built-in protected-path floor is additive and cannot be removed by omitting `[protected_paths]`.
- The init template writes the built-in floor explicitly so operators can see the default guardrails and add project-specific paths.

## ADR-015 — Copilot CLI tool permissions and timeout are configurable

| Field | Decision |
|---|---|
| Status | Accepted |
| Scope | Phase 5 |

`CopilotCliAdapter` tool permissions (`--allow-tool`, `--deny-tool`) and subprocess timeout are read from a `[copilot_cli]` section in `.wfrunner/wfrunner.toml` instead of being hardcoded.

Rationale:

- Different projects may need different security postures for tool access.
- Timeout may need adjustment for large steps or slow environments.
- Users should be able to customize without editing source code.

Consequences:

- A `CopilotCliConfig` frozen dataclass is added to `tools/config.py`.
- `CopilotCliAdapter` builds flags from config instead of inline constants.
- The `timeout_seconds` constructor parameter is removed from `CopilotCliAdapter`.

## ADR-016 — Git commit and push behavior

| Field | Decision |
|---|---|
| Status | Accepted; `commit_per_step` superseded (auto-commit standardized) |
| Scope | Phase 5 |

`run()` commits every successful `IMPLEMENTATION` step automatically, and `_git_commit()` conditionally runs `git push` based on `[git].push_required`.

Rationale:

- Some workflows operate on local branches without pushing (offline, review batching, local experimentation), so `git push` remains controllable.
- Unconditional `git push` is a side effect that should be controllable.
- Per-step commits give reliable rollback points and a clean commit range for scoped code review, so they are always on rather than optional.

Consequences:

- A `GitConfig` frozen dataclass includes `push_required`.
- `_git_commit()` skips `git push` when `push_required` is `False`.
- `push_required` defaults to `true` in the init template.
- Every successful `IMPLEMENTATION` step is committed; the retired `commit_per_step` toggle no longer exists.

## ADR-017 — GitChangeDetector uses "renamed" change type for rename destinations

| Field | Decision |
|---|---|
| Status | Accepted |
| Scope | Phase 5 |

When `GitChangeDetector` detects a Git rename (`R` status), the source path is emitted with change type `"deleted"` and the destination path is emitted with change type `"renamed"` (not `"created"`).

Rationale:

- `check_allowed_files()` documents `"renamed"` as a valid change type.
- Scope enforcer tests model renames as `{"destination": "renamed"}`.
- Emitting `"created"` for rename destinations causes a representation mismatch between the detector and the enforcer contract.
- Both source and destination must be in `allowed_files` for a rename to pass scope checks.

Consequences:

- `GitChangeDetector.detect_changes()` emits `"renamed"` instead of `"created"` for rename destination paths.
- The mtime-based fallback in `retry_controller.py` is removed in favor of requiring the `ChangeDetector` abstraction.

## ADR-018 — Use one `wfrunner` CLI with subcommands

| Field | Decision |
|---|---|
| Status | Accepted |
| Scope | Phase 7 |

The user-facing CLI is `tools/wfrunner.py` with subcommands: `run`, `validate`, `status`, and `init`.

Rationale:

- A single entry point is easier to document, package, and test.
- `run_plan.py` should own orchestration functions, not argument parsing.
- `validate_plan.py` should own validation functions, not a standalone CLI.

Consequences:

- `run_plan.py` exports orchestration functions such as `prepare_run()`, `reset_run()`, `reset_current_step()`, and `run()`.
- Removed legacy flat run flags stay removed; equivalent behavior now lives in subcommands, config, or next-step mode where applicable.
- `wfrunner run` uses a required plan path and config-loaded defaults.
- `wfrunner validate` can run without config, validating protected-path rules against the built-in protected-path floor in that case.

## ADR-019 — Script command results distinguish FAIL from ERROR

| Field | Decision |
|---|---|
| Status | Accepted |
| Scope | Phase 7 |

Pre-analysis and verification command runners use `ScriptOutcome` values: `PASS`, `FAIL`, and `ERROR`.

Rationale:

- A command that successfully reports a product/test failure is different from a broken script, timeout, or runner exception.
- Broken diagnostics should block automation rather than trigger implementation retries.

Consequences:

- `FAIL` maps to `FAILED` for implementation pre-analysis and verification.
- Verification `FAIL` may enter the configured retry loop.
- `ERROR` maps to `BLOCKED` and does not retry.

## ADR-020 — Human gates can be explicitly auto-approved

| Field | Decision |
|---|---|
| Status | Accepted |
| Scope | Phase 7.2 |

`wfrunner run` accepts `--approve-human-gates` for unattended runs whose gates have been reviewed in advance.

Rationale:

- Some whole-plan runs need to proceed through known gates without manual editing of progress during execution.
- Gate pre-analysis still provides a safety check before auto-approval.

Consequences:

- Without the flag, `HUMAN_GATE` behavior is unchanged: the orchestrator stops at the gate.
- With the flag, a gate without pre-analysis is marked `DONE` and execution continues.
- With the flag and gate pre-analysis, `PASS` marks `DONE`, `FAIL` marks `FAILED`, and `ERROR` marks `BLOCKED`.

## ADR-021 — Use whole-plan naming for run-until-stop mode

| Field | Decision |
|---|---|
| Status | Accepted |
| Scope | Phase 7.2 |

The run-until-stop mode is called whole-plan mode, and the report is `whole-plan-report.md`.

Rationale:

- The mode is about plan coverage, not time of day.
- Naming should match the actual behavior and be clear in logs and reports.

Consequences:

- The report generator is `generate_whole_plan_report()`.
- The report heading is `# Whole-Plan Report`.
- The previous time-of-day report name is no longer part of the active contract.

## ADR-022 — Package metadata is the version source of truth

| Field | Decision |
|---|---|
| Status | Accepted |
| Scope | Phase 7.2 |

The project version is read from package metadata, with `pyproject.toml` as the source of truth.

Rationale:

- Duplicating `__version__` in runtime code creates drift.
- PyInstaller packaging should include all `tools.*` modules needed by the unified CLI.
- The separate `fix-verification.md` prompt is obsolete because retry uses the implementation prompt plus `failure_context`.

Consequences:

- `tools/wfrunner.py` resolves `__version__` through `importlib.metadata` with a development fallback.
- `wfrunner.spec` includes the needed `tools.*` hidden imports.
- `prompts/fix-verification.md` is not part of the active prompt set.
