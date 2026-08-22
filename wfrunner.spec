# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for WaterfallRunner.

Produces a single wfrunner executable at dist/wfrunner.exe.
"""

import os

from PyInstaller.utils.hooks import copy_metadata

block_cipher = None

# Provide no-op stubs when running outside PyInstaller (e.g. syntax check).
try:
    Analysis
except NameError:
    class _Stub:
        def __init__(self, *a, **kw):
            self.pure = []
            self.scripts = []
            self.binaries = []
            self.datas = []
    Analysis = _Stub
    PYZ = _Stub
    EXE = _Stub
    COLLECT = _Stub

_hidden_imports = [
    "tools",
    "tools.config",
    "tools.constants",
    "tools.data_path",
    "tools.init_project",
    "tools.plan_parser",
    "tools.plan_validator",
    "tools.review_base",
    "tools.run_plan",
    "tools.wfrunner",
    "tools.validate_plan",
    "tools.orchestrator",
    "tools.orchestrator.agent_adapter",
    "tools.orchestrator.agent_invocation",
    "tools.orchestrator.change_detector",
    "tools.orchestrator.copilot_cli_adapter",
    "tools.orchestrator.pre_analysis_runner",
    "tools.orchestrator.progress_manager",
    "tools.orchestrator.report_generator",
    "tools.orchestrator.retry_controller",
    "tools.orchestrator.run_logger",
    "tools.orchestrator.scope_enforcer",
    "tools.orchestrator.step_selector",
    "tools.orchestrator.verification",
]

_datas = copy_metadata("wfrunner") + [
    ("schemas/*.json", "schemas"),
    ("prompts/system_prompt.implementation.md", "prompts"),
    ("prompts/system_prompt.analysis.md", "prompts"),
    (".github/skills/wfrunner-planner/SKILL.md", ".github/skills/wfrunner-planner"),
    (".github/skills/wfrunner-planner/references/*.md", ".github/skills/wfrunner-planner/references"),
    (".github/skills/wfrunner-planner/scripts/*.py", ".github/skills/wfrunner-planner/scripts"),
]

# --- Analysis for wfrunner (tools/wfrunner.py) ---
a = Analysis(
    ["tools/wfrunner.py"],
    pathex=[],
    binaries=[],
    datas=_datas,
    hiddenimports=_hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    exclude_binaries=False,
    name="wfrunner",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    # Extract to the system temp dir (PyInstaller default). Extracting into the
    # current working directory instead unpacks a transient _MEIxxxxxx/ dir into
    # the target repo, polluting its Git worktree and breaking clean-tree
    # detection (blocks IMPLEMENTATION steps). See FINDING-010 / R10.11.
    runtime_tmpdir=None,
)
