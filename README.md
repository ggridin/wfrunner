# WaterfallRunner

WaterfallRunner is a local, specs-driven orchestration project for controlled AI-assisted implementation.

The goal is to provide a deterministic controller around coding agents: validate an implementation plan, run one bounded step at a time, enforce file scope, run objective verification, record progress, and stop when human judgment is required.

## Status

This repository is currently focused on Phase 1 of the project. The Phase 1 scope is to prove that a structured implementation plan can drive controlled step-by-step AI-assisted work without building a new coding agent.

## What WaterfallRunner Does

- Validates implementation-plan metadata and workflow rules
- Parses Markdown plans into structured steps
- Executes steps in strict document order
- Enforces `allowed_files` after agent execution
- Runs orchestrator-owned verification commands
- Supports bounded retry after verification failure
- Produces runtime progress, logs, and `whole-plan-report.md` under the configured `.wfrunner/automation` directory

## Repository Layout

- `docs/`: implementation plan and project documentation
- `docs/specs/`: architecture, contracts, design, operations, and test scenarios
- `schemas/`: JSON Schema files used for validation
- `tools/`: validator and orchestrator Python modules
- `tools/orchestrator/`: orchestration components such as step selection, scope enforcement, retry, verification, and reporting
- `prompts/`: reusable prompt templates for agent invocation
- `.github/agents/`: custom agent definitions
- `tests/`: pytest test suite

## Requirements

- Python 3.11+
- Git
- Optional for future agent integration: GitHub Copilot CLI

## Development Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .[dev]
```

## Common Commands

Validate the implementation plan:

```powershell
python -m tools.wfrunner validate docs/implementation-plan.md
```

Run the test suite:

```powershell
python -m pytest tests/ -v
```

Show CLI help for the orchestrator:

```powershell
python -m tools.wfrunner run --help
```

Show current progress for a plan:

```powershell
python -m tools.wfrunner status docs/implementation-plan.md
```

Initialize a target project:

```powershell
wfrunner init
```

The init command is parameterless. It creates the local WaterfallRunner config, the per-type system prompts, the `default.wfrunner` agent, and the maintained `wfrunner-planner` skill under `.github\skills\wfrunner-planner\`.

Build and smoke-check the packaged executable:

```powershell
python build.py
dist\wfrunner.exe --version
dist\wfrunner.exe --help
dist\wfrunner.exe run --help
dist\wfrunner.exe validate docs\implementation-plan.md
dist\wfrunner.exe status docs\implementation-plan.md
```

Run `dist\wfrunner.exe init` from a disposable Git repository to verify first-project bootstrap behavior. The canonical release artifact is `dist\wfrunner.exe`; do not validate a copied root-level executable as a fresh build.

## Notes

- Runtime artifacts are written under the configured `.wfrunner/automation` directory and are ignored by Git.
- The main run summary is `whole-plan-report.md`.
- The implementation plan is intended to stay immutable during execution; runtime state is tracked separately.
- Protected files such as schemas, prompts, and core orchestration guardrails require explicit human review in the workflow design.

## License

This project is licensed under the MIT License. See the `LICENSE` file.