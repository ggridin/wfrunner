"""Tests for the unified wfrunner CLI subcommand interface (Phase 7)."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from tests.helpers import (
    make_default_config,
    make_implementation_step,
    make_plan,
    make_progress,
    write_progress,
)
from tools.config import ConfigNotFoundError


# ---------------------------------------------------------------------------
# Parser tests — STEP-001
# ---------------------------------------------------------------------------


class TestSubcommandRecognition:
    """Each subcommand name is recognized by the parser."""

    @pytest.mark.parametrize("subcmd", ["run", "validate", "status", "init", "review-base"])
    def test_subcommand_recognized(self, subcmd: str) -> None:
        from tools.wfrunner import build_parser

        parser = build_parser()
        if subcmd in ("run", "validate", "status"):
            args = parser.parse_args([subcmd, "plan.md"])
        else:
            args = parser.parse_args([subcmd])
        assert args.subcommand == subcmd


class TestPublicCliSurfaceContract:
    """The packaged public CLI exposes only supported Phase 1 workflows."""

    @pytest.mark.parametrize("subcmd", ["run", "validate", "status", "init", "review-base"])
    def test_supported_public_subcommands_are_recognized(self, subcmd: str) -> None:
        from tools.wfrunner import build_parser

        parser = build_parser()
        if subcmd in ("run", "validate", "status"):
            args = parser.parse_args([subcmd, "docs/plan.md"])
        else:
            args = parser.parse_args([subcmd])

        assert args.subcommand == subcmd

    @pytest.mark.parametrize("argv", [
        ["compile", "docs/plan.md"],
        ["codereview", "--model", "gpt-4", "--agent", "reviewer", "--base-branch", "main"],
    ])
    def test_internal_or_unimplemented_subcommands_are_not_public(self, argv: list[str]) -> None:
        from tools.wfrunner import build_parser

        parser = build_parser()

        with pytest.raises(SystemExit):
            parser.parse_args(argv)

    def test_global_init_alias_is_not_public(self) -> None:
        from tools.wfrunner import build_parser

        parser = build_parser()

        with pytest.raises(SystemExit):
            parser.parse_args(["--init"])


class TestValidateSubcommand:
    """Validate accepts positional plan_path and optional --config."""

    def test_validate_plan_path(self) -> None:
        from tools.wfrunner import build_parser

        parser = build_parser()
        args = parser.parse_args(["validate", "docs/plan.md"])
        assert args.plan_path == "docs/plan.md"

    def test_validate_with_config(self) -> None:
        from tools.wfrunner import build_parser

        parser = build_parser()
        args = parser.parse_args(["validate", "docs/plan.md", "--config", "my.toml"])
        assert args.config == "my.toml"

    def test_validate_without_config(self) -> None:
        from tools.wfrunner import build_parser

        parser = build_parser()
        args = parser.parse_args(["validate", "docs/plan.md"])
        assert args.config is None


class TestRunSubcommand:
    """Run accepts positional plan_path and all expected flags."""

    def test_run_plan_path(self) -> None:
        from tools.wfrunner import build_parser

        parser = build_parser()
        args = parser.parse_args(["run", "docs/plan.md"])
        assert args.plan_path == "docs/plan.md"

    def test_run_with_config(self) -> None:
        from tools.wfrunner import build_parser

        parser = build_parser()
        args = parser.parse_args(["run", "docs/plan.md", "--config", "my.toml"])
        assert args.config == "my.toml"

    def test_run_prepare_only(self) -> None:
        from tools.wfrunner import build_parser

        parser = build_parser()
        args = parser.parse_args(["run", "docs/plan.md", "--prepare-only"])
        assert args.prepare_only is True

    def test_run_next_step_only(self) -> None:
        from tools.wfrunner import build_parser

        parser = build_parser()
        args = parser.parse_args(["run", "docs/plan.md", "--next-step-only"])
        assert args.next_step_only is True

    def test_run_resume(self) -> None:
        from tools.wfrunner import build_parser

        parser = build_parser()
        args = parser.parse_args(["run", "docs/plan.md", "--resume"])
        assert args.resume is True

    def test_run_reset(self) -> None:
        from tools.wfrunner import build_parser

        parser = build_parser()
        args = parser.parse_args(["run", "docs/plan.md", "--reset"])
        assert args.reset is True

    def test_run_reset_current_step(self) -> None:
        from tools.wfrunner import build_parser

        parser = build_parser()
        args = parser.parse_args(["run", "docs/plan.md", "--reset-current-step"])
        assert args.reset_current_step is True

    def test_run_approve_human_gates(self) -> None:
        from tools.wfrunner import build_parser

        parser = build_parser()
        args = parser.parse_args(["run", "docs/plan.md", "--approve-human-gates"])
        assert args.approve_human_gates is True

    def test_run_approve_human_gates_defaults_false(self) -> None:
        from tools.wfrunner import build_parser

        parser = build_parser()
        args = parser.parse_args(["run", "docs/plan.md"])
        assert args.approve_human_gates is False


class TestStatusSubcommand:
    """Status accepts positional plan_path."""

    def test_status_plan_path(self) -> None:
        from tools.wfrunner import build_parser

        parser = build_parser()
        args = parser.parse_args(["status", "docs/plan.md"])
        assert args.plan_path == "docs/plan.md"


class TestInitSubcommand:
    """Init delegates to tools.init_project.init()."""

    def test_init_calls_init_project(self) -> None:
        from tools.wfrunner import main

        with mock.patch("tools.wfrunner.init_project_init", return_value=0) as mock_init:
            exit_code = main(["init"])
        mock_init.assert_called_once()
        assert exit_code == 0


class TestReviewBaseSubcommand:
    """review-base exposes record and diff for scoped codereview baselines."""

    def test_review_base_record_args(self) -> None:
        from tools.wfrunner import build_parser

        parser = build_parser()
        args = parser.parse_args(["review-base", "record", "--file", "base.sha"])
        assert args.subcommand == "review-base"
        assert args.review_base_command == "record"
        assert args.file == "base.sha"

    def test_review_base_diff_args(self) -> None:
        from tools.wfrunner import build_parser

        parser = build_parser()
        args = parser.parse_args(
            ["review-base", "diff", "--base-file", "base.sha", "--out", "diff.patch"]
        )
        assert args.review_base_command == "diff"
        assert args.base_file == "base.sha"
        assert args.out == "diff.patch"

    def test_review_base_record_dispatches(self, tmp_path: Path) -> None:
        from tools.wfrunner import main

        sha_file = tmp_path / "base.sha"
        with mock.patch(
            "tools.wfrunner.review_base.record", return_value=0
        ) as mock_record:
            exit_code = main(["review-base", "record", "--file", str(sha_file)])
        mock_record.assert_called_once()
        assert exit_code == 0

    def test_review_base_diff_dispatches(self, tmp_path: Path) -> None:
        from tools.wfrunner import main

        with mock.patch(
            "tools.wfrunner.review_base.diff", return_value=0
        ) as mock_diff:
            exit_code = main(
                ["review-base", "diff", "--base-file", "b.sha", "--out", "d.patch"]
            )
        mock_diff.assert_called_once()
        assert exit_code == 0

    def test_review_base_without_action_returns_error(self) -> None:
        from tools.wfrunner import main

        assert main(["review-base"]) == 2


class TestVersionFlag:
    """--version prints version and exits."""

    def test_version_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        from tools.wfrunner import main

        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "0.1.0" in captured.out


class TestVersionResolution:
    """Version resolution supports installed packages, source trees, and frozen builds."""

    def test_get_version_prefers_package_metadata(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from tools import wfrunner

        monkeypatch.setattr(
            wfrunner.importlib_metadata,
            "version",
            lambda distribution: "9.8.7",
        )

        assert wfrunner._get_version() == "9.8.7"

    def test_get_version_falls_back_to_source_pyproject(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from tools import wfrunner

        def raise_missing_metadata(_distribution: str) -> str:
            raise wfrunner.importlib_metadata.PackageNotFoundError

        source_root = tmp_path / "checkout"
        tools_dir = source_root / "tools"
        tools_dir.mkdir(parents=True)
        (source_root / "pyproject.toml").write_text(
            '[project]\nversion = "4.5.6"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(wfrunner, "__file__", str(tools_dir / "wfrunner.py"))
        monkeypatch.setattr(
            wfrunner.importlib_metadata,
            "version",
            raise_missing_metadata,
        )

        assert wfrunner._get_version() == "4.5.6"

    def test_get_version_returns_unknown_when_metadata_and_source_are_missing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from tools import wfrunner

        def raise_missing_metadata(_distribution: str) -> str:
            raise wfrunner.importlib_metadata.PackageNotFoundError

        source_root = tmp_path / "frozen"
        tools_dir = source_root / "tools"
        tools_dir.mkdir(parents=True)
        monkeypatch.setattr(wfrunner, "__file__", str(tools_dir / "wfrunner.py"))
        monkeypatch.setattr(
            wfrunner.importlib_metadata,
            "version",
            raise_missing_metadata,
        )

        assert wfrunner._get_version() == "unknown"


class TestPyInstallerSpec:
    """Packaging spec includes distribution metadata for frozen version lookup."""

    def test_wfrunner_spec_copies_package_metadata(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        spec_text = (project_root / "wfrunner.spec").read_text(encoding="utf-8")

        assert "from PyInstaller.utils.hooks import copy_metadata" in spec_text
        assert 'copy_metadata("wfrunner")' in spec_text


class TestReleaseSmokeExitCodes:
    """Release smoke commands declare expected executable exit codes."""

    def test_release_smoke_exit_code_contract_is_explicit(self) -> None:
        import build

        exit_codes = {command.name: command.expected_exit_code for command in build.RELEASE_SMOKE_COMMANDS}

        assert exit_codes == {
            "version": 0,
            "help": 0,
            "run-help": 0,
            "validate": 0,
            "status": 0,
            "init": 0,
            "review-base": 0,
        }

    def test_missing_runtime_resource_exit_code_contract_is_explicit(self) -> None:
        from tools import wfrunner

        assert wfrunner.PACKAGING_ERROR_EXIT_CODE == 2


class TestReadmeCommandExamples:
    """README examples should describe the active unified CLI surface."""

    @staticmethod
    def _readme_text() -> str:
        project_root = Path(__file__).resolve().parents[1]
        return (project_root / "README.md").read_text(encoding="utf-8")

    def test_readme_uses_unified_cli_examples(self) -> None:
        readme = self._readme_text()

        assert "python tools/validate_plan.py" not in readme
        assert "python tools/run_plan.py" not in readme
        assert "python -m tools.wfrunner validate" in readme or "wfrunner validate" in readme
        assert "python -m tools.wfrunner run --help" in readme or "wfrunner run --help" in readme

    def test_readme_uses_current_runtime_artifact_names(self) -> None:
        readme = self._readme_text()

        assert "overnight report" not in readme.lower()
        assert "overnight reports" not in readme.lower()
        assert "`.automation/`" not in readme
        assert ".wfrunner/automation" in readme
        assert "whole-plan-report.md" in readme

    def test_readme_mentions_status_command(self) -> None:
        readme = self._readme_text()

        assert "wfrunner status" in readme or "python -m tools.wfrunner status" in readme


class TestPublicCliDocumentation:
    """Docs should advertise only supported public CLI commands."""

    @staticmethod
    def _active_cli_docs() -> str:
        project_root = Path(__file__).resolve().parents[1]
        paths = (
            project_root / "README.md",
            project_root / "docs" / "specs" / "Phase1_contracts.md",
            project_root / "docs" / "specs" / "Phase1_operations.md",
        )
        return "\n".join(path.read_text(encoding="utf-8") for path in paths)

    def test_docs_do_not_advertise_removed_or_internal_commands(self) -> None:
        docs = self._active_cli_docs()

        assert "wfrunner compile" not in docs
        assert "wfrunner codereview" not in docs
        assert "--init" not in docs

    def test_docs_advertise_supported_public_commands(self) -> None:
        docs = self._active_cli_docs()

        assert "wfrunner run" in docs
        assert "wfrunner validate" in docs
        assert "wfrunner status" in docs
        assert "wfrunner init" in docs


class TestNoArguments:
    """No arguments prints help and exits with error."""

    def test_no_args_exits_with_error(self) -> None:
        from tools.wfrunner import main

        exit_code = main([])
        assert exit_code != 0


# ---------------------------------------------------------------------------
# Handler tests — STEP-009
# ---------------------------------------------------------------------------


class TestValidateHandler:
    """Validate handler dispatches plan validation and reports results."""

    def test_valid_plan_with_config_exits_0(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        from tools.wfrunner import main

        plan_text = make_plan(
            make_implementation_step("STEP-001", title="First step"),
            make_implementation_step("STEP-002", title="Second step"),
        )
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")

        config = make_default_config()
        with mock.patch("tools.wfrunner.load_config", return_value=config):
            exit_code = main(["validate", str(plan_file), "--config", "wfrunner.toml"])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "2" in captured.out  # step count

    def test_valid_plan_without_config_exits_0(
        self, tmp_path: Path,
    ) -> None:
        from tools.wfrunner import main

        plan_text = make_plan(
            make_implementation_step("STEP-001", title="First step"),
        )
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")

        # No config file found → ConfigNotFoundError → skip protected-paths
        with mock.patch(
            "tools.wfrunner.load_config",
            side_effect=ConfigNotFoundError("no config"),
        ):
            exit_code = main(["validate", str(plan_file)])

        assert exit_code == 0

    def test_invalid_plan_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        from tools.wfrunner import main

        # A plan with duplicate step IDs is invalid
        plan_text = make_plan(
            make_implementation_step("STEP-001", title="First"),
            make_implementation_step("STEP-001", title="Duplicate"),
        )
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")

        with mock.patch(
            "tools.wfrunner.load_config",
            side_effect=ConfigNotFoundError("no config"),
        ):
            exit_code = main(["validate", str(plan_file)])

        assert exit_code == 1
        captured = capsys.readouterr()
        out = captured.out + captured.err
        # Should mention errors
        assert len(out) > 0

    def test_explicit_config_protected_paths_are_used_for_validation(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from tools.wfrunner import main

        cwd = tmp_path / "cwd"
        cwd.mkdir()
        monkeypatch.chdir(cwd)
        monkeypatch.setattr("tools.config.user_config_path", lambda: tmp_path / "missing-user.toml")

        plan_text = make_plan(
            make_implementation_step(
                "STEP-001",
                title="Touch configured protected path",
                allowed_files=["custom/guarded.py"],
            ),
        )
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")
        config_file = tmp_path / "explicit-wfrunner.toml"
        config_file.write_text(
            """
default_model = "default"

[protected_paths]
paths = ["custom/"]
""".lstrip(),
            encoding="utf-8",
        )

        exit_code = main(["validate", str(plan_file), "--config", str(config_file)])

        assert exit_code == 1

    def test_plan_file_not_found_exits_2(
        self,
    ) -> None:
        from tools.wfrunner import main

        exit_code = main(["validate", "/nonexistent/plan.md"])
        assert exit_code == 2


class TestStatusHandler:
    """Status handler shows step progress from plan + progress.json."""

    def test_plan_with_progress_exits_0(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        from tools.wfrunner import main

        plan_text = make_plan(
            make_implementation_step("STEP-001", title="First step"),
            make_implementation_step("STEP-002", title="Second step"),
        )
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")

        automation_dir = tmp_path / ".wfrunner" / "automation"
        progress = make_progress(
            steps={
                "STEP-001": {"state": "DONE"},
                "STEP-002": {"state": "TODO"},
            },
            plan_file="plan.md",
        )
        write_progress(automation_dir / "progress.json", progress)

        config = make_default_config(automation_dir=str(automation_dir))
        with mock.patch("tools.wfrunner.load_config", return_value=config):
            exit_code = main(["status", str(plan_file)])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "STEP-001" in captured.out
        assert "STEP-002" in captured.out

    def test_plan_with_no_progress_exits_0(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        from tools.wfrunner import main

        plan_text = make_plan(
            make_implementation_step("STEP-001", title="First step"),
        )
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")

        # No progress file exists — automation dir is empty
        automation_dir = tmp_path / ".wfrunner" / "automation"
        config = make_default_config(automation_dir=str(automation_dir))
        with mock.patch("tools.wfrunner.load_config", return_value=config):
            exit_code = main(["status", str(plan_file)])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "No execution data found" in captured.out

    def test_plan_with_no_progress_and_no_config_exits_0(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from tools.wfrunner import main

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("tools.config.user_config_path", lambda: tmp_path / "missing-user.toml")
        plan_text = make_plan(
            make_implementation_step("STEP-001", title="First step"),
        )
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")

        exit_code = main(["status", str(plan_file)])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "No execution data found." in captured.out

    def test_explicit_config_status_uses_configured_automation_dir(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from tools.wfrunner import main

        plan_text = make_plan(
            make_implementation_step("STEP-001", title="First step"),
        )
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")
        automation_dir = tmp_path / "configured-automation"
        progress = make_progress(
            steps={"STEP-001": {"state": "DONE"}},
            plan_file="plan.md",
        )
        write_progress(automation_dir / "progress.json", progress)
        config_file = tmp_path / "explicit-wfrunner.toml"
        config_file.write_text('default_model = "default"\n', encoding="utf-8")

        config = make_default_config(automation_dir=str(automation_dir))
        with mock.patch("tools.wfrunner.load_config", return_value=config) as mock_load_config:
            exit_code = main(["status", str(plan_file), "--config", str(config_file)])

        assert exit_code == 0
        mock_load_config.assert_called_once_with(config_file=config_file)
        captured = capsys.readouterr()
        assert "STEP-001" in captured.out
        assert "DONE" in captured.out

    def test_plan_file_not_found_exits_2(
        self,
    ) -> None:
        from tools.wfrunner import main

        exit_code = main(["status", "/nonexistent/plan.md"])
        assert exit_code == 2


# ---------------------------------------------------------------------------
# Run handler integration tests — STEP-013
# ---------------------------------------------------------------------------


class TestRunHandler:
    """Run subcommand handler dispatches to run_plan functions."""

    def test_prepare_only_calls_prepare_run(self, tmp_path: Path) -> None:
        from tools.wfrunner import main

        plan_text = make_plan(
            make_implementation_step("STEP-001", "First"),
        )
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")

        config = make_default_config(automation_dir=str(tmp_path / ".automation"))
        with (
            mock.patch("tools.wfrunner.load_config", return_value=config),
            mock.patch("tools.wfrunner._load_run_config", return_value=config),
            mock.patch("tools.run_plan.prepare_run", return_value={"error": None}) as mock_prepare,
        ):
            exit_code = main(["run", str(plan_file), "--prepare-only"])

        assert exit_code == 0
        mock_prepare.assert_called_once()

    def test_prepare_only_with_explicit_config_passes_exact_file_to_loader(
        self,
        tmp_path: Path,
    ) -> None:
        from tools.wfrunner import main

        plan_text = make_plan(
            make_implementation_step("STEP-001", "First"),
        )
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(plan_text, encoding="utf-8")
        config_file = tmp_path / "wfrunner.toml"
        config_file.write_text('default_model = "default"\n', encoding="utf-8")

        config = make_default_config(automation_dir=str(tmp_path / ".automation"))
        with (
            mock.patch("tools.wfrunner.load_config", return_value=config) as mock_load_config,
            mock.patch("tools.run_plan.prepare_run", return_value={"error": None}),
        ):
            exit_code = main(["run", str(plan_file), "--config", str(config_file), "--prepare-only"])

        assert exit_code == 0
        mock_load_config.assert_called_once_with(config_file=config_file)

    def test_prepare_only_with_approve_human_gates_warns(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from tools.wfrunner import main

        plan_file = tmp_path / "plan.md"
        plan_file.write_text("# Plan\n", encoding="utf-8")

        config = make_default_config()
        with (
            mock.patch("tools.wfrunner._load_run_config", return_value=config),
            mock.patch("tools.run_plan.prepare_run", return_value={"error": None}),
        ):
            exit_code = main(["run", str(plan_file), "--prepare-only", "--approve-human-gates"])

        assert exit_code == 0
        captured = capsys.readouterr()
        output = captured.out + captured.err
        assert "approve-human-gates" in output
        assert "prepare-only" in output

    def test_default_run_calls_run_with_prepared_context(self, tmp_path: Path) -> None:
        from tools.wfrunner import main

        plan_file = tmp_path / "plan.md"
        plan_file.write_text("# Plan\n", encoding="utf-8")

        config = make_default_config()
        ctx = {"error": None, "plan_path": plan_file}
        with (
            mock.patch("tools.wfrunner._load_run_config", return_value=config),
            mock.patch("tools.run_plan.prepare_run", return_value=ctx) as mock_prepare,
            mock.patch("tools.run_plan.run", return_value=7) as mock_run,
        ):
            exit_code = main(["run", str(plan_file)])

        assert exit_code == 7
        mock_prepare.assert_called_once_with(str(plan_file), config, resume=False)
        mock_run.assert_called_once_with(ctx, one_step=False, approve_human_gates=False)

    def test_next_step_only_calls_run_one_step(self, tmp_path: Path) -> None:
        from tools.wfrunner import main

        plan_file = tmp_path / "plan.md"
        plan_file.write_text("# Plan\n", encoding="utf-8")

        config = make_default_config()
        ctx = {"error": None, "plan_path": plan_file}
        with (
            mock.patch("tools.wfrunner._load_run_config", return_value=config),
            mock.patch("tools.run_plan.prepare_run", return_value=ctx),
            mock.patch("tools.run_plan.run", return_value=0) as mock_run,
        ):
            exit_code = main(["run", str(plan_file), "--next-step-only"])

        assert exit_code == 0
        mock_run.assert_called_once_with(ctx, one_step=True, approve_human_gates=False)

    def test_approve_human_gates_calls_run_with_flag(self, tmp_path: Path) -> None:
        from tools.wfrunner import main

        plan_file = tmp_path / "plan.md"
        plan_file.write_text("# Plan\n", encoding="utf-8")

        config = make_default_config()
        ctx = {"error": None, "plan_path": plan_file}
        with (
            mock.patch("tools.wfrunner._load_run_config", return_value=config),
            mock.patch("tools.run_plan.prepare_run", return_value=ctx),
            mock.patch("tools.run_plan.run", return_value=0) as mock_run,
        ):
            exit_code = main(["run", str(plan_file), "--approve-human-gates"])

        assert exit_code == 0
        mock_run.assert_called_once_with(ctx, one_step=False, approve_human_gates=True)

    def test_reset_calls_reset_run(self, tmp_path: Path) -> None:
        from tools.wfrunner import main

        plan_file = tmp_path / "plan.md"
        plan_file.write_text("# Plan\n", encoding="utf-8")

        config = make_default_config()
        with (
            mock.patch("tools.wfrunner._load_run_config", return_value=config),
            mock.patch("tools.run_plan.reset_run", return_value=0) as mock_reset,
        ):
            exit_code = main(["run", str(plan_file), "--reset"])

        assert exit_code == 0
        mock_reset.assert_called_once()

    def test_reset_current_step_calls_reset(self, tmp_path: Path) -> None:
        from tools.wfrunner import main

        plan_file = tmp_path / "plan.md"
        plan_file.write_text("# Plan\n", encoding="utf-8")

        config = make_default_config()
        with (
            mock.patch("tools.wfrunner._load_run_config", return_value=config),
            mock.patch("tools.run_plan.reset_current_step", return_value=0) as mock_reset_step,
        ):
            exit_code = main(["run", str(plan_file), "--reset-current-step"])

        assert exit_code == 0
        mock_reset_step.assert_called_once()

    def test_missing_config_exits_with_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        from tools.wfrunner import main

        plan_file = tmp_path / "plan.md"
        plan_file.write_text("# Plan\n", encoding="utf-8")

        with mock.patch(
            "tools.wfrunner._load_run_config",
            side_effect=ConfigNotFoundError("no config"),
        ):
            exit_code = main(["run", str(plan_file)])

        assert exit_code != 0
        captured = capsys.readouterr()
        out = captured.out + captured.err
        assert len(out) > 0
