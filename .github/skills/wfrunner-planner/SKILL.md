---
name: wfrunner-planner
description: >
  Create, modify, review, and renumber WaterfallRunner implementation plans and
  steps. Use for plan-format questions, STEP metadata, HUMAN_GATE placement,
  allowed_files scopes, protected paths, validation fixes, and contiguous step
  numbering workflows.
---

# WaterfallRunner Planner

Use this skill when working on WaterfallRunner implementation plans, especially
when creating steps, modifying existing plans, inserting HUMAN_GATE reviews, or
renumbering STEP IDs.

## Accepted Input

- Product requirements, architecture notes, bug-fix plans, or implementation
  requests that must become a WaterfallRunner plan.
- Existing `docs/implementation-plan.md` style plans that need new steps,
  inserted steps, HUMAN_GATE reviews, allowed file changes, or renumbering.
- Validation output from `tools/plan_parser.py`, `tools/plan_validator.py`, or
  `schemas/implementation-step.schema.json`.

## Create vs Modify

- Create a new plan when the user provides source material but no target plan.
- Modify an existing plan when the user names a plan file or asks to append,
  insert, split, reorder, or repair steps.
- Insert a minor step such as `STEP-004.001` for local edits between existing
  steps, then use the renumbering workflow when the user wants contiguous IDs.
- Add a `HUMAN_GATE` before protected-path changes or unresolved decisions.

## Quick Reference

| Do | Don't |
| --- | --- |
| Use `### STEP-001 - Title` headings with one YAML block per step. | Add custom YAML fields that the schema does not allow. |
| Keep `allowed_files` strict, repository-relative, and complete. | Treat verification prose as a substitute for executable commands. |
| Use `IMPLEMENTATION` only for file-changing work. | Put `agent`, `allowed_files`, or `retry` on `HUMAN_GATE` steps. |
| Validate after plan edits and after renumbering. | Leave duplicate, skipped, or non-contiguous step IDs. |

## Workflow

1. Read the source material and the current plan, if one exists.
2. Convert work into strictly ordered steps; Phase 1 dependency order is
   document order.
3. Choose `IMPLEMENTATION` for file changes and `HUMAN_GATE` for decisions,
   approvals, ambiguity, or protected-file review.
4. If the source design would force a clear SOLID concern, re-decompose steps
  when that is only a planning change; otherwise raise it with a `HUMAN_GATE`.
5. Populate metadata from the schema, keeping prose and YAML consistent.
6. Run validation and repair plan structure before finalizing.

## Code review and fix steps

WaterfallRunner ships two optional agents for a review/fix loop. They reuse existing
step types, so no new step type or schema field is required.

- **codereview** runs as an `ANALYSIS` step. Set `agent: codereview`, a `model`
  (a stronger review model is fine), and `artifact_files` for the findings
  report it must write. The step is read-only and cannot modify source.
- **codefix** runs as an `IMPLEMENTATION` step. Set `agent: codefix`,
  `allowed_files` for the source it may change, plus `verification` and `retry`.
  Name the review's findings file in the task prose so the fixer reads it; keep
  that findings file out of `allowed_files` (it is read-only input).

Scope the review to the plan's own changes with a portable baseline:

- Add a **Record review baseline** `ANALYSIS` step as the first step; its
  `pre_analysis` runs `python -m tools.review_base record` to capture `HEAD`
  (create-if-absent, resume-safe).
- The `codereview` step's `pre_analysis` runs `python -m tools.review_base diff`
  to write a `base..HEAD` unified patch into its artifacts; the reviewer reads
  that patch. This assumes auto-commit is on so the range captures the plan's
  work.
- If git is unavailable the helper emits a fallback marker and the reviewer
  reviews the union of the plan's `allowed_files`, so name those files in the
  review step's prose. Findings are Markdown with a `yaml` summary block.
- See [WaterfallRunner conventions](./references/wfrunner-conventions.md) for a
  full baseline + review + fix example.

Placement:

- Short plans: add the `codereview` step and then the `codefix` step as the
  last two steps.
- Long plans: insert a `codereview`/`codefix` pair at phase boundaries. Use
  minor IDs while drafting (for example `STEP-004.001` review, `STEP-004.002`
  fix), then renumber to contiguous IDs.

A clean review yields a no-op fix: an `IMPLEMENTATION` step that changes nothing
still passes scope and verification, so the pair is safe to include by default.

## References

- [Plan format](./references/plan-format.md)
- [Plan modification](./references/plan-modification.md)
- [WaterfallRunner conventions](./references/wfrunner-conventions.md), including
  plan design principles, SOLID design concerns, and review findings format

