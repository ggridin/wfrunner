# WaterfallRunner Architecture

## Short summary

WaterfallRunner is a local, specs-driven orchestration project for controlled AI-assisted implementation.

The project does not try to replace GitHub Copilot, Copilot CLI, Visual Studio, or future coding agents. Its purpose is to provide a deterministic controller around coding agents: validate the implementation plan, run one bounded task at a time, enforce scope, verify results, log decisions, and stop when human judgment is required.

## Project purpose

WaterfallRunner exists to make AI-assisted implementation more disciplined and auditable.

The core problem is not that AI coding agents cannot produce useful code. The problem is that long-running AI coding workflows can drift, skip steps, modify unexpected files, continue past risky decisions, or leave weak evidence about what happened.

WaterfallRunner addresses this by treating the implementation plan as a contract and the coding agent as a bounded worker.

## Goals

- Convert a structured implementation plan into controlled step-by-step execution.
- Keep workflow control outside the AI coding agent.
- Validate implementation-plan metadata before execution.
- Execute one bounded step at a time.
- Enforce allowed file changes.
- Run objective verification commands after agent execution.
- Stop at explicit human gates, failures, or safety violations.
- Produce durable progress, logs, reports, and Git checkpoints.
- Keep the design simple enough for a senior engineer to understand, test, and maintain.

## Non-goals

- Build a new general-purpose coding agent.
- Build a custom LLM coding engine.
- Replace GitHub Copilot, Copilot CLI, Visual Studio, Aider, Claude Code, OpenHands, or other coding agents.
- Build a cloud platform.
- Build a multi-user product.
- Build a complex workflow engine.
- Execute multiple repositories in Phase 1.
- Implement parallel execution in Phase 1.
- Automatically merge work to `main`.

## Core principles

### The specification is the contract

The implementation plan is not casual notes. It is a structured, version-controlled contract that must be readable by humans, parseable by tools, and validated before execution.

### The schema is human-owned

The schema defines the allowed structure of the implementation plan. AI may suggest schema changes, but ordinary implementation agents must not weaken the schema or bypass it.

### The orchestrator owns workflow control

The coding agent performs work. WaterfallRunner decides what work is allowed, when work starts, when work stops, what files may change, what verification proves success, and what gets logged.

### Agent output is not trusted by itself

An agent may claim success, but WaterfallRunner verifies success independently through Git status, allowlist checks, command exit codes, progress state, and reports.

### Human gates are explicit

Risky operations are represented by explicit `HUMAN_GATE` steps. The system should not infer human approval from metadata.

### Git commits are checkpoints

A successful step may be committed independently, creating a rollback point and an auditable history.

## Top-level architecture

WaterfallRunner has four conceptual layers:

| Layer | Responsibility |
|---|---|
| Human planning layer | Create and review implementation plans. |
| Contract layer | Validate plan structure and workflow rules. |
| Orchestration layer | Select the next step, invoke agents, enforce scope, run verification, update progress, and stop safely. |
| Worker-agent layer | Execute one bounded step using Copilot CLI custom agents or another future worker. |

## Trust boundaries

| Component | Trusted for | Not trusted for |
|---|---|---|
| Human | Intent, approval, architecture judgment | Perfect manual consistency |
| JSON Schema and validator | Structural correctness | Semantic quality of the plan |
| Orchestrator | Workflow control and enforcement | Proving business correctness by itself |
| Copilot agent | Implementing bounded tasks | Deciding scope, approval, or final success |
| Verification commands | Objective command results | Proving all possible correctness |

## Repository-level concept

A WaterfallRunner-enabled repository contains:

| Area | Purpose |
|---|---|
| `docs/` | Implementation plan and project documentation. |
| `schemas/` | Human-owned metadata schemas. |
| `tools/` | Validator and orchestrator scripts. |
| `.github/agents/` | Copilot CLI custom agent definitions. |
| `prompts/` | Reusable prompt templates. |
| `.wfrunner/` | User-local runtime configuration (`wfrunner.toml`). Git-ignored. |
| `<automation_dir>/` | Runtime progress, logs, verification outputs, reports, and patches. Default `.wfrunner/automation/`. |

## Reference basis

This architecture is aligned with the following current documentation themes:

- GitHub Copilot CLI supports project-local custom agents defined as Markdown agent files under `.github/agents/`.
- GitHub Copilot CLI supports programmatic invocation for automation workflows.
- JSON Schema Draft 2020-12 is suitable for declaring and validating structured JSON/YAML-derived data contracts.
- Python `jsonschema` supports validating instances against JSON Schema.
