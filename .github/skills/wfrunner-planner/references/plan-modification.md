# Plan Modification

Modify WaterfallRunner plans with small, traceable edits. Preserve existing source
material and keep step order as the dependency model.

## Appending Steps

Append new work after the final step when it naturally follows the existing
plan. Use the next contiguous major ID, for example `STEP-014` after
`STEP-013`.

Before appending, check whether the new work needs a preceding `HUMAN_GATE` for
protected paths, unclear requirements, security review, or operational
acceptance.

## Inserting Steps

When a step must be inserted between two existing major steps, use a minor ID:

```markdown
### STEP-006.001 - Add focused regression test
```

Minor IDs let reviewers see the local insertion without renumbering the rest of
the plan. Keep minor IDs contiguous under their major step.

## Renumbering Workflow

Use the planner script when the user asks to normalize or flatten step IDs:

```powershell
python .github\skills\wfrunner-planner\scripts\renumber_steps.py --plan docs\implementation-plan.md
python .github\skills\wfrunner-planner\scripts\renumber_steps.py --plan docs\implementation-plan.md --write
```

The default mode is a dry run. It reports the new numbering and validates the
renumbered content without changing the file. `--write` updates headings and
YAML `id` values after validation succeeds.

## Protected Path Rules

Protected paths require a preceding `HUMAN_GATE` before an implementation step
changes them:

- `schemas/`
- `tools/validate_plan.py`
- `tools/run_plan.py`
- `.github/agents/`
- `.github/copilot-instructions.md`
- `prompts/`

Do not hide protected changes inside broad `allowed_files` entries. Name the
exact protected files that will change and make the gate decision explicit.

## Validation After Modification

After any plan edit, run the repository validation command for the target plan.
Validation checks parsing, schema compliance, duplicate IDs, heading/YAML
consistency, and step ordering through `tools/plan_parser.py` and
`tools/plan_validator.py`.

## Contiguity Rules

- Major IDs must be contiguous and ordered from `STEP-001`.
- Minor IDs must be contiguous within their parent major.
- A minor ID must have a preceding bare major step.
- After flattening, no `STEP-###.###` IDs should remain.

