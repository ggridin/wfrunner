# WaterfallRunner Agent Design — Agents, Skills, and Prompts

## Short summary

This document records the design assumptions for how WaterfallRunner separates concerns across agents, skills, and prompts. The goal is clear role separation that works reliably across different target projects and invocation modes (interactive VS Code, headless Copilot CLI).

## Design principle

WaterfallRunner is a controller that orchestrates external coding agents. It must work across arbitrary target projects. It cannot assume any specific project has `.instructions.md`, `SKILL.md`, or other customization files. Therefore, WaterfallRunner's own behavioral contracts must be self-contained in agents and prompts — the two primitives guaranteed to be loaded during CLI invocation.

## Agents — personas with goals

Agents are personas that pursue specific goals. Each agent file (`.agent.md`) defines:

- **Identity**: who the agent is and what it does.
- **Behavioral contract**: constraints, quality expectations, and boundaries specific to the role.
- **Result contract**: the JSON schema the orchestrator expects back.
- **Tool permissions**: the minimal toolset the role requires.

Agents are self-contained. They must work correctly even when no `.instructions.md` or `SKILL.md` files are loaded in the session. This is because headless CLI runs (`copilot --agent X --autopilot`) are not guaranteed to load workspace instruction files.

### Current agents

| Agent | Goal |
|---|---|
| `default.wfrunner` | Generic, language-agnostic software developer; the default worker persona. Users bring their own agent via the step `agent` field to override it. |

The bounded-step execution rules and the result-JSON contract no longer live in the agent; they are carried by per-type WaterfallRunner system prompts (see below) so that any bring-your-own agent can be driven safely.

### Future agents

| Agent | Goal |
|---|---|
| `spec-planner` | Build or refine a fully actionable, schema-valid implementation plan. Shares the same project conventions as other WaterfallRunner agents. |

### What belongs in agents vs. elsewhere

| In the agent persona | In the WaterfallRunner system prompt / elsewhere |
|---|---|
| Role identity and goal | Bounded-step execution rules and result contract (system prompt) |
| Quality expectations for the role | Step-specific parameters: `step_id`, `allowed_files` (assembled metadata) |
| Adaptation to the target project's conventions | Protected-path and scope constraints (system prompt + orchestrator) |
| — | Failure context for retries; pre-analysis output |

## Skills — target project guidelines (discovery-based)

Skills are guidelines for the target project being worked on — not for WaterfallRunner itself. They are loaded on demand when the agent's description matches, or referenced explicitly.

WaterfallRunner cannot enforce their presence. Target projects may or may not have them. WaterfallRunner agents must degrade gracefully when no skills are available: the agent body carries enough behavioral contract to function correctly, and the orchestrator enforces guardrails independently (scope enforcement, verification, protected paths).

`wfrunner init` installs the maintained `wfrunner-planner` skill into the target project by default. The skill is a planning aid for interactive authoring and validation repair; it is not an executable guardrail and is not required for headless step execution.

### When skills help

- Target project has coding conventions (naming, framework patterns, test structure) that benefit from being documented as a skill.
- The skill is too large or too project-specific to inline into every agent body.
- Interactive VS Code sessions can discover and load the skill automatically.

### When skills are insufficient

- Headless CLI runs may not discover or load skills.
- Safety-critical guardrails (protected paths, allowed_files) must not depend on skill loading — the orchestrator Python layer enforces them.

## Prompts — system prompts and compiled step prose

WaterfallRunner owns two prompt layers, both assembled in code by the adapter. There is no per-step template file, and the worker never reads the source plan.

- **Per-type system prompts** (`prompts/system_prompt.implementation.md`, `prompts/system_prompt.analysis.md`) carry the bounded-step execution rules and the result-JSON contract. The system prompt for the step's `type` is injected on every invocation, independent of which agent runs.
- **The compiled step prompt** is the step's Markdown task prose, lifted from the plan body into the compiled artifact as the `prompt` string and injected directly as the task.

Plans must provide non-empty project description text. Worker-backed steps must
also provide non-empty task prose: all `IMPLEMENTATION` steps, and any
`ANALYSIS` step that declares `agent`/`model`. Command-only `ANALYSIS` steps may
omit task prose because no worker message is assembled for them.

### What the assembled worker message contains

- The per-type system prompt (execution rules + result contract).
- The shared plan context (project description), materialized once as a compiled runtime artifact.
- The compiled step prompt (task prose).
- Structured metadata: `step_id`, `title`, `allowed_files`, `verification_commands`.
- Failure context appended on retry after verification `FAIL`.

### What does NOT belong in the assembled message

- A pointer to the source plan file or an instruction to locate the step there.
- Coding quality rules (these live in the agent persona or target project skills).
- Pre-analysis output beyond bounded excerpts.
- Protected-path lists (the orchestrator enforces these independently).

### Why the system prompt is injected every time

The selected agent persona is bring-your-own and may carry no WaterfallRunner rules. The per-type system prompt guarantees that the bounded-step contract (single step, `allowed_files` only, no deletions, no plan or `.wfrunner/automation` edits, result JSON) is present on every invocation regardless of which agent runs.

## Protected paths — YAML rules and Git enforcement

Protected paths are enforced at two layers:

| Layer | Mechanism | Guarantee |
|---|---|---|
| Plan validation | YAML `allowed_files` checked against protected-path list; changes require a preceding `HUMAN_GATE` step. | Catches violations before execution. |
| Orchestrator enforcement | `scope_enforcer.py` + `change_detector.py` inspect actual Git working-tree changes after agent execution. | Catches violations that bypass plan rules. |

Protected paths have a non-removable built-in floor, and `.wfrunner/wfrunner.toml` can add project-specific paths under the `[protected_paths]` section. The init template writes the built-in floor explicitly. Enforcement is performed by the orchestrator Python layer, not by skills or instructions. This ensures enforcement regardless of whether skills/instructions are loaded.

Agents do not need awareness of specific protected paths. The orchestrator enforces them independently after agent execution.

## Layered reliability model

| Layer | Loaded when | Purpose |
|---|---|---|
| Agent persona | Always (specified by `--agent` name; bring-your-own, defaults to `default.wfrunner`) | Developer persona that adapts to the target project |
| System prompt (per type) | Always (injected by the orchestrator on every invocation) | Bounded-step execution rules and result contract |
| Step prompt + plan context | Always (assembled by the orchestrator, passed to CLI) | Task prose, plan context, and step metadata |
| Target project instructions/skills | When present and discoverable | Project conventions (coding style, patterns) |
| Orchestrator Python enforcement | Always (runs independently of agent) | Hard guardrails: scope, protected paths, verification |

The first three layers are guaranteed. The fourth is beneficial but optional. The fifth is authoritative.

## Drift mitigation

The main risk of having constraints in both agent bodies and prompts is **drift** — updating one but not the other. Mitigation:

- Prompts carry only a brief reminder, not a full restatement. The agent body is the source of truth.
- The orchestrator enforcement layer is the authoritative gate, independent of what agents or prompts say.
- The plan validator catches structural issues (missing `allowed_files`, missing `HUMAN_GATE` before protected paths) before execution begins.

## File conventions

| File type | Location | Extension | Naming |
|---|---|---|---|
| Agents | `.github/agents/` | `.agent.md` | Lowercase, hyphenated role name |
| Prompts | `prompts/` | `.md` | Lowercase, hyphenated action name |
| Skills | `.github/skills/<name>/` | `SKILL.md` | Directory name = skill name |
| Instructions | `.github/instructions/` | `.instructions.md` | Descriptive name |
