"""Tests for tools.plan_parser — covers parsing, error handling, and edge cases."""

from __future__ import annotations

import textwrap

from tools.plan_parser import ParseResult, parse_plan


# ---------------------------------------------------------------------------
# Happy-path parsing
# ---------------------------------------------------------------------------


class TestParseValidPlans:
    """Tests for correctly formed plans."""

    def test_single_implementation_step(self) -> None:
        text = textwrap.dedent("""\
            # Plan

            ## Implementation plan

            ### STEP-001 — Set up project

            ```yaml
            schema_version: 1
            id: STEP-001
            title: Set up project
            type: IMPLEMENTATION
            agent: spec-implementer
            prompt: prompts/implement-step.md
            model: default
            allowed_files:
              - pyproject.toml
            verification:
              commands:
                - "python -c \\"print(1)\\""
            retry:
              max_fix_attempts: 0
            ```
        """)
        result = parse_plan(text)
        assert result.ok
        assert len(result.steps) == 1
        step = result.steps[0]
        assert step.heading_id == "STEP-001"
        assert step.heading_title == "Set up project"
        assert step.yaml_block["type"] == "IMPLEMENTATION"
        assert step.yaml_block["allowed_files"] == ["pyproject.toml"]

    def test_single_human_gate_step(self) -> None:
        text = textwrap.dedent("""\
            # Plan

            ### STEP-001 — Review code

            ```yaml
            schema_version: 1
            id: STEP-001
            title: Review code
            type: HUMAN_GATE
            description: Check everything.
            ```
        """)
        result = parse_plan(text)
        assert result.ok
        assert len(result.steps) == 1
        assert result.steps[0].yaml_block["type"] == "HUMAN_GATE"

    def test_multiple_steps(self) -> None:
        text = textwrap.dedent("""\
            # Plan

            ### STEP-001 — First step

            ```yaml
            schema_version: 1
            id: STEP-001
            title: First step
            type: HUMAN_GATE
            ```

            ### STEP-002 — Second step

            ```yaml
            schema_version: 1
            id: STEP-002
            title: Second step
            type: HUMAN_GATE
            ```
        """)
        result = parse_plan(text)
        assert result.ok
        assert len(result.steps) == 2
        assert result.steps[0].heading_id == "STEP-001"
        assert result.steps[1].heading_id == "STEP-002"

    def test_paragraph_between_heading_and_yaml(self) -> None:
        text = textwrap.dedent("""\
            # Plan

            ### STEP-001 — With description

            This step does important things.

            ```yaml
            schema_version: 1
            id: STEP-001
            title: With description
            type: HUMAN_GATE
            ```
        """)
        result = parse_plan(text)
        assert result.ok
        assert len(result.steps) == 1

    def test_heading_with_en_dash(self) -> None:
        text = textwrap.dedent("""\
            ### STEP-001 \u2014 En dash title

            ```yaml
            schema_version: 1
            id: STEP-001
            title: En dash title
            type: HUMAN_GATE
            ```
        """)
        result = parse_plan(text)
        assert result.ok

    def test_line_numbers_are_one_based(self) -> None:
        text = "### STEP-001 — A step\n\n```yaml\nschema_version: 1\nid: STEP-001\ntitle: A step\ntype: HUMAN_GATE\n```\n"
        result = parse_plan(text)
        assert result.ok
        assert result.steps[0].heading_line_number == 1
        assert result.steps[0].yaml_line_number == 4  # line after ```yaml


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestParseErrors:
    """Tests for malformed plans."""

    def test_missing_yaml_block(self) -> None:
        """VAL-003: Missing YAML metadata block."""
        text = textwrap.dedent("""\
            ### STEP-001 — No yaml

            No YAML block here at all.

            ### STEP-002 — Another heading

            ```yaml
            schema_version: 1
            id: STEP-002
            title: Another heading
            type: HUMAN_GATE
            ```
        """)
        result = parse_plan(text)
        assert not result.ok
        assert any("missing YAML" in e.message for e in result.errors)

    def test_malformed_yaml(self) -> None:
        """VAL-004: Malformed YAML."""
        text = textwrap.dedent("""\
            ### STEP-001 — Bad yaml

            ```yaml
            schema_version: 1
            id: STEP-001
            title: Bad yaml
            type: [not, valid
            ```
        """)
        result = parse_plan(text)
        assert not result.ok
        assert any("Malformed YAML" in e.message for e in result.errors)

    def test_unclosed_yaml_fence(self) -> None:
        text = textwrap.dedent("""\
            ### STEP-001 — Unclosed

            ```yaml
            schema_version: 1
            id: STEP-001
        """)
        result = parse_plan(text)
        assert not result.ok
        assert any("Unclosed" in e.message for e in result.errors)

    def test_non_mapping_yaml(self) -> None:
        text = textwrap.dedent("""\
            ### STEP-001 — List yaml

            ```yaml
            - one
            - two
            ```
        """)
        result = parse_plan(text)
        assert not result.ok
        assert any("mapping" in e.message for e in result.errors)

    def test_empty_plan(self) -> None:
        result = parse_plan("")
        assert result.ok
        assert len(result.steps) == 0

    def test_no_step_headings(self) -> None:
        text = "# Plan\n\nSome text but no steps.\n"
        result = parse_plan(text)
        assert result.ok
        assert len(result.steps) == 0


# ---------------------------------------------------------------------------
# Parse result properties
# ---------------------------------------------------------------------------


class TestParseResult:
    """Tests for ParseResult behavior."""

    def test_ok_property_true_when_no_errors(self) -> None:
        r = ParseResult()
        assert r.ok

    def test_ok_property_false_when_errors(self) -> None:
        from tools.plan_parser import ParseError
        r = ParseResult(errors=[ParseError(line_number=1, message="oops")])
        assert not r.ok


# ---------------------------------------------------------------------------
# Minor step ID parsing (STEP-NNN.NNN)
# ---------------------------------------------------------------------------


class TestParseMinorStepIDs:
    """Tests for parsing minor (sub-step) IDs like STEP-003.001."""

    def test_minor_step_id_parsed_as_heading_id(self) -> None:
        """### STEP-003.001 — Title is parsed with heading_id STEP-003.001."""
        text = textwrap.dedent("""\
            # Plan

            ### STEP-003.001 — Sub-step title

            ```yaml
            schema_version: 1
            id: STEP-003.001
            title: Sub-step title
            type: HUMAN_GATE
            ```
        """)
        result = parse_plan(text)
        assert result.ok, f"Parse errors: {result.errors}"
        assert len(result.steps) == 1
        assert result.steps[0].heading_id == "STEP-003.001"
        assert result.steps[0].heading_title == "Sub-step title"

    def test_major_step_id_still_works(self) -> None:
        """### STEP-003 — Title continues to parse as before."""
        text = textwrap.dedent("""\
            # Plan

            ### STEP-003 — Regular title

            ```yaml
            schema_version: 1
            id: STEP-003
            title: Regular title
            type: HUMAN_GATE
            ```
        """)
        result = parse_plan(text)
        assert result.ok, f"Parse errors: {result.errors}"
        assert len(result.steps) == 1
        assert result.steps[0].heading_id == "STEP-003"

    def test_minor_step_id_extracted_from_yaml(self) -> None:
        """YAML id field with minor numbering is extracted correctly."""
        text = textwrap.dedent("""\
            # Plan

            ### STEP-002.003 — YAML minor step

            ```yaml
            schema_version: 1
            id: STEP-002.003
            title: YAML minor step
            type: HUMAN_GATE
            ```
        """)
        result = parse_plan(text)
        assert result.ok, f"Parse errors: {result.errors}"
        assert len(result.steps) == 1
        assert result.steps[0].yaml_block["id"] == "STEP-002.003"

    def test_mixed_major_and_minor_steps_parsed(self) -> None:
        """A plan with both major and minor steps parses all of them."""
        text = textwrap.dedent("""\
            # Plan

            ### STEP-001 — Major step

            ```yaml
            schema_version: 1
            id: STEP-001
            title: Major step
            type: HUMAN_GATE
            ```

            ### STEP-001.001 — First sub-step

            ```yaml
            schema_version: 1
            id: STEP-001.001
            title: First sub-step
            type: HUMAN_GATE
            ```

            ### STEP-001.002 — Second sub-step

            ```yaml
            schema_version: 1
            id: STEP-001.002
            title: Second sub-step
            type: HUMAN_GATE
            ```
        """)
        result = parse_plan(text)
        assert result.ok, f"Parse errors: {result.errors}"
        assert len(result.steps) == 3
        assert result.steps[0].heading_id == "STEP-001"
        assert result.steps[1].heading_id == "STEP-001.001"
        assert result.steps[2].heading_id == "STEP-001.002"
