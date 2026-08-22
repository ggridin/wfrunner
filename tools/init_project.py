"""Scaffold a .wfrunner/ project directory with default configuration."""

from __future__ import annotations

from pathlib import Path
from shutil import copy2

from tools.config import BUILTIN_PROTECTED_PATHS, DEFAULT_CONFIG
from tools.data_path import get_project_root, require_runtime_resource

_SENTINEL_START = "# >>> WaterfallRunner managed >>>"
_SENTINEL_END = "# <<< WaterfallRunner managed <<<"
_GITIGNORE_ENTRIES = [
    "/.wfrunner/",
    "/.wfrunner/automation/plan.compiled.json",
    ".github/agents/default.wfrunner.agent.md",
    ".github/agents/codereview.agent.md",
    ".github/agents/codefix.agent.md",
]

_AGENT_TEMPLATE = """\
---
description: >
  Generic, language-agnostic software developer. The default WaterfallRunner worker
  persona; bring your own agent to override it.
---

# default.wfrunner

You are a careful, experienced software developer. You adapt to the conventions
of the codebase in front of you and prefer the smallest correct change that
satisfies the task.

WaterfallRunner injects the applicable bounded-step execution rules as a system
prompt on every invocation, so this persona carries no WaterfallRunner-specific
rules.
"""

_CODEREVIEW_AGENT_TEMPLATE = """\
---
description: >
  Language-agnostic code reviewer for WaterfallRunner ANALYSIS steps. Reviews the
  plan's own changes from a supplied diff and writes a findings report; never
  modifies source files.
---

# codereview

You are a meticulous, language-agnostic code reviewer. You run inside a
WaterfallRunner ANALYSIS step, so your work is strictly read-only: you inspect the
change set and record what you find.

WaterfallRunner injects the applicable bounded-step execution rules as a system
prompt on every invocation. In addition:

## Scope

- Review only this plan's changes. Your task names a unified diff patch
  (produced by `tools.review_base`); read it and review those changes.
- If that patch begins with `# codereview: no diff available` (git was
  unavailable or no baseline was recorded), fall back to reviewing the files
  your task lists (the union of the plan's `allowed_files`).
- You may open any file for context, but keep findings focused on the change
  set, not the whole repository.

## Output

- Do not modify, create, or delete any Git-tracked source file. Write your
  review only to the step's declared `artifact_files`.
- Write the report as Markdown that opens with a fenced `yaml` findings block,
  then any short explanatory notes needed for human context.
- Use this severity rubric:
  - `blocker`: correctness, data-loss, security, or scope issue that should stop
    the change from landing.
  - `major`: important defect or maintainability issue that should be fixed
    before relying on the change.
  - `minor`: localized improvement that is worth fixing but does not undermine
    the main behavior.
  - `nit`: small clarity, style, or wording issue that is optional.
- Review these dimensions: correctness and logic, edge cases, error handling,
  security, resource cleanup, test adequacy, and adherence to the change's
  intent.
- Use stable finding IDs so a follow-up fix step can report outcomes by ID.
  Match this structure:

```yaml
reviewed:
  base: .wfrunner/analysis/plan-base.sha
  patch: .wfrunner/analysis/STEP-050-review.patch
findings: 2
by_severity:
  blocker: 0
  major: 1
  minor: 1
  nit: 0
items:
  - id: REVIEW-001
    severity: major
    location: tools/parser.py:42
    problem: Parser accepts an empty step title, which later progress output cannot identify clearly.
    suggested_fix: Reject empty titles during plan parsing and cover the case with a parser test.
  - id: REVIEW-002
    severity: minor
    location: tests/test_parser.py:88
    problem: The new parser test duplicates setup already provided by a helper.
    suggested_fix: Reuse the existing plan-fragment helper to keep the fixture concise.
```

- If you find nothing worth changing, record zero findings and say so
  explicitly rather than inventing issues.
- A review that records findings is still a completed review: return
  `status: DONE`, not failure, unless you were unable to perform the review.
"""

_CODEFIX_AGENT_TEMPLATE = """\
---
description: >
  Language-agnostic fixer for WaterfallRunner IMPLEMENTATION steps. Reads a code
  review's findings and applies the smallest correct changes within scope.
---

# codefix

You are a careful, language-agnostic software developer. You run inside a
WaterfallRunner IMPLEMENTATION step whose task references a review findings file
produced by an earlier `codereview` step.

WaterfallRunner injects the applicable bounded-step execution rules as a system
prompt on every invocation. In addition:

- Read the findings report named in your task before changing anything. It is
  Markdown that opens with a structured `yaml` findings block containing
  `reviewed`, `findings`, `by_severity`, and an `items` list with stable finding
  IDs.
- Address actionable findings in severity order: blocker, major, minor, then
  nit. Within the same severity, keep the report order.
- Address the findings with the smallest correct change, and touch only the
  files listed in `allowed_files`. The findings file itself is read-only input.
- If a finding is out of scope for the declared `allowed_files`, leave it and
  report `skipped-out-of-scope` for that finding ID rather than widening scope.
- If a finding is invalid, already handled, or no longer applies, decline it by
  ID and report `declined-invalid` with a short note.
- For each finding ID, report one outcome in your result: `fixed`,
  `skipped-out-of-scope`, or `declined-invalid`.
- Treat the orchestrator's verification commands as authoritative over the
  findings file. If verification fails, fix the verified behavior within scope;
  if verification passes and there are no actionable findings, make no changes
  and say so in your result.
- If there are no actionable findings, make no changes and say so in your
  result.
"""

_AGENT_TEMPLATES: dict[str, str] = {
    "default.wfrunner.agent.md": _AGENT_TEMPLATE,
    "codereview.agent.md": _CODEREVIEW_AGENT_TEMPLATE,
    "codefix.agent.md": _CODEFIX_AGENT_TEMPLATE,
}


def init(target_dir: Path | None = None) -> int:
    """Scaffold .wfrunner/ config, prompts, agent file, and .gitignore entries.

    Args:
        target_dir: Project root to scaffold into. Defaults to CWD.

    Returns:
        0 on success.
    """
    root = Path.cwd() if target_dir is None else Path(target_dir)

    _create_config(root)
    _copy_prompts(root)
    _scaffold_agents(root)
    _copy_planner_skill(root)
    _update_gitignore(root)

    return 0


def _toml_bool(value: bool) -> str:
    """Render a Python bool as a TOML boolean literal."""
    return "true" if value else "false"


def _render_config() -> str:
    """Render the default wfrunner.toml body from the shared defaults.

    Values come from tools.config.DEFAULT_CONFIG so the generated file can never
    drift from the loader's built-in fallbacks.
    """
    protected_paths = "".join(f'  "{path}",\n' for path in BUILTIN_PROTECTED_PATHS)
    return (
        f'default_model = "{DEFAULT_CONFIG["default_model"]}"\n'
        f'automation_dir = "{DEFAULT_CONFIG["automation_dir"]}"\n'
        f'copilot_command = "{DEFAULT_CONFIG["copilot_command"]}"\n'
        f'default_agent = "{DEFAULT_CONFIG["default_agent"]}"\n'
        f'git_timeout_seconds = {DEFAULT_CONFIG["git_timeout_seconds"]}\n'
        f'git_push_timeout_seconds = {DEFAULT_CONFIG["git_push_timeout_seconds"]}\n'
        f'pre_analysis_timeout_seconds = {DEFAULT_CONFIG["pre_analysis_timeout_seconds"]}\n'
        '\n'
        '[git]\n'
        f'push_required = {_toml_bool(DEFAULT_CONFIG["git"]["push_required"])}\n'
        '\n'
        '[protected_paths]\n'
        'paths = [\n'
        f'{protected_paths}'
        ']\n'
    )


def _create_config(root: Path) -> None:
    config_path = root / ".wfrunner" / "wfrunner.toml"
    if config_path.exists():
        print(f"  skip  {config_path.relative_to(root)} (already exists)")
        return
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(_render_config(), encoding="utf-8")
    print(f"  create  {config_path.relative_to(root)}")


def _copy_prompts(root: Path) -> None:
    dst_dir = root / ".wfrunner" / "prompts"
    dst_dir.mkdir(parents=True, exist_ok=True)
    for name in ("system_prompt.implementation.md", "system_prompt.analysis.md"):
        dst = dst_dir / name
        if dst.exists():
            print(f"  skip  {dst.relative_to(root)} (already exists)")
            continue
        src = require_runtime_resource(
            Path("prompts") / name,
            description=f"system prompt {name}",
        )
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"  create  {dst.relative_to(root)}")


def _scaffold_agents(root: Path) -> None:
    agents_dir = root / ".github" / "agents"
    for filename, template in _AGENT_TEMPLATES.items():
        agent_path = agents_dir / filename
        if agent_path.exists():
            print(f"  skip  {agent_path.relative_to(root)} (already exists)")
            continue
        agent_path.parent.mkdir(parents=True, exist_ok=True)
        agent_path.write_text(template, encoding="utf-8")
        print(f"  create  {agent_path.relative_to(root)}")


def _copy_planner_skill(root: Path) -> None:
    src_dir = get_project_root() / ".github" / "skills" / "wfrunner-planner"
    if not src_dir.is_dir():
        raise FileNotFoundError(f"Missing wfrunner-planner skill template directory: {src_dir}")

    dst_dir = root / ".github" / "skills" / "wfrunner-planner"
    for src in sorted(path for path in src_dir.rglob("*") if path.is_file()):
        relative_path = src.relative_to(src_dir)
        dst = dst_dir / relative_path
        if dst.exists():
            print(f"  skip  {dst.relative_to(root)} (already exists)")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        copy2(src, dst)
        print(f"  create  {dst.relative_to(root)}")


def _update_gitignore(root: Path) -> None:
    gitignore_path = root / ".gitignore"
    block = _SENTINEL_START + "\n"
    for entry in _GITIGNORE_ENTRIES:
        block += entry + "\n"
    block += _SENTINEL_END + "\n"

    if gitignore_path.exists():
        content = gitignore_path.read_text(encoding="utf-8")
        if _SENTINEL_START in content:
            # Replace existing block in place.
            start = content.index(_SENTINEL_START)
            end = content.index(_SENTINEL_END) + len(_SENTINEL_END)
            # Include trailing newline if present.
            if end < len(content) and content[end] == "\n":
                end += 1
            content = content[:start] + block + content[end:]
            gitignore_path.write_text(content, encoding="utf-8")
            print("  update  .gitignore (WaterfallRunner block refreshed)")
            return
        # Append block.
        if not content.endswith("\n"):
            content += "\n"
        content += "\n" + block
        gitignore_path.write_text(content, encoding="utf-8")
    else:
        gitignore_path.write_text(block, encoding="utf-8")
    print("  update  .gitignore")
