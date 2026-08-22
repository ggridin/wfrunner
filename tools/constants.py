"""Named constants for WaterfallRunner — YAML field names, enumerations, and canonical strings."""

from __future__ import annotations

from enum import Enum


# ---------------------------------------------------------------------------
# Script execution outcome (three-state model)
# ---------------------------------------------------------------------------

class ScriptOutcome(Enum):
    """Three-state result for script execution (pre-analysis, verification).

    PASS:  exit code 0 — proceed.
    FAIL:  well-formed nonzero exit — step FAILED.
    ERROR: script itself crashed (FileNotFoundError, timeout, unexpected) — step BLOCKED.
    """

    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"

# ---------------------------------------------------------------------------
# YAML field names (step metadata)
# ---------------------------------------------------------------------------

FIELD_SCHEMA_VERSION = "schema_version"
FIELD_ID = "id"
FIELD_TITLE = "title"
FIELD_TYPE = "type"
FIELD_AGENT = "agent"
FIELD_PROMPT = "prompt"
FIELD_MODEL = "model"
FIELD_ALLOWED_FILES = "allowed_files"
FIELD_PRE_ANALYSIS = "pre_analysis"
FIELD_VERIFICATION = "verification"
FIELD_COMMANDS = "commands"
FIELD_RETRY = "retry"
FIELD_MAX_FIX_ATTEMPTS = "max_fix_attempts"
FIELD_DESCRIPTION = "description"
FIELD_ARTIFACT_FILES = "artifact_files"
FIELD_SOURCE_FILE = "source_file"
FIELD_SOURCE_SHA256 = "source_sha256"
FIELD_PLAN_DESCRIPTION = "plan_description"
FIELD_METADATA = "metadata"
FIELD_REVIEW_GUIDANCE = "review_guidance"

# ---------------------------------------------------------------------------
# Step types
# ---------------------------------------------------------------------------

STEP_TYPE_IMPLEMENTATION = "IMPLEMENTATION"
STEP_TYPE_HUMAN_GATE = "HUMAN_GATE"
STEP_TYPE_ANALYSIS = "ANALYSIS"

# ---------------------------------------------------------------------------
# Model resolution
# ---------------------------------------------------------------------------

# Sentinel model value meaning "defer to the configured default_model".
# When resolution leaves this value in place (default_model is also the
# sentinel), the agent CLI selection is omitted so the CLI picks its own default.
MODEL_DEFAULT = "default"

# Sentinel agent value meaning "defer to the configured default_agent".
AGENT_DEFAULT = "default"

# ---------------------------------------------------------------------------
# Step states (progress)
# ---------------------------------------------------------------------------

STATE_TODO = "TODO"
STATE_IN_PROGRESS = "IN_PROGRESS"
STATE_DONE = "DONE"
STATE_FAILED = "FAILED"
STATE_BLOCKED = "BLOCKED"
STATE_SKIPPED = "SKIPPED"

# ---------------------------------------------------------------------------
# Agent result statuses
# ---------------------------------------------------------------------------

AGENT_STATUS_DONE = "DONE"
AGENT_STATUS_FAILED = "FAILED"
AGENT_STATUS_BLOCKED = "BLOCKED"

# ---------------------------------------------------------------------------
# Failure reason codes
# ---------------------------------------------------------------------------

FAILURE_HUMAN_GATE = "HUMAN_GATE"
FAILURE_SCOPE_VIOLATION = "SCOPE_VIOLATION"
FAILURE_DIRTY_WORKTREE = "DIRTY_WORKTREE"
FAILURE_AGENT_BLOCKED = "AGENT_BLOCKED"
FAILURE_INVALID_AGENT_RESULT = "INVALID_AGENT_RESULT"
FAILURE_VERIFICATION_FAILED = "VERIFICATION_FAILED"
FAILURE_PRE_ANALYSIS_FAILED = "PRE_ANALYSIS_FAILED"
FAILURE_CHANGE_DETECTION_UNAVAILABLE = "CHANGE_DETECTION_UNAVAILABLE"

# ---------------------------------------------------------------------------
# Stop reasons
# ---------------------------------------------------------------------------

STOP_ALL_COMPLETE = "ALL_STEPS_COMPLETE"
STOP_ONE_STEP = "ONE_STEP"
STOP_HUMAN_GATE = "HUMAN_GATE"
STOP_BLOCKED = "BLOCKED"
STOP_FAILED = "FAILED"
STOP_SCOPE_VIOLATION = "SCOPE_VIOLATION"
STOP_PRE_ANALYSIS_FAILED = "PRE_ANALYSIS_FAILED"
STOP_VERIFICATION_FAILED = "VERIFICATION_FAILED"
STOP_DIRTY_WORKTREE = "DIRTY_WORKTREE"
STOP_AGENT_BLOCKED = "AGENT_BLOCKED"
STOP_INVALID_AGENT_RESULT = "INVALID_AGENT_RESULT"

# ---------------------------------------------------------------------------
# Scope violation reasons
# ---------------------------------------------------------------------------

VIOLATION_NOT_IN_ALLOWED = "not_in_allowed_files"
VIOLATION_PROTECTED_FILE = "protected_file"

# ---------------------------------------------------------------------------
# Verification statuses
# ---------------------------------------------------------------------------

VERIFY_PASS = "PASS"
VERIFY_FAIL = "FAIL"
VERIFY_TIMEOUT = "TIMEOUT"
VERIFY_WARN = "WARN"

# ---------------------------------------------------------------------------
# Progress field names
# ---------------------------------------------------------------------------

PROGRESS_FIELD_STATE = "state"
PROGRESS_FIELD_AGENT = "agent"
PROGRESS_FIELD_MODEL = "model"
PROGRESS_FIELD_STARTED_AT = "started_at"
PROGRESS_FIELD_COMPLETED_AT = "completed_at"
PROGRESS_FIELD_PRE_ANALYSIS = "pre_analysis"
PROGRESS_FIELD_VERIFICATION = "verification"
PROGRESS_FIELD_FIX_ATTEMPTS = "fix_attempts"
PROGRESS_FIELD_COMMIT = "commit"
PROGRESS_FIELD_FAILURE_REASON = "failure_reason"
PROGRESS_FIELD_PLAN_FILE = "plan_file"
PROGRESS_FIELD_LAST_RUN_ID = "last_run_id"
PROGRESS_FIELD_STEPS = "steps"
PROGRESS_FIELD_SCHEMA_VERSION = "schema_version"

# ---------------------------------------------------------------------------
# Failure reason dict keys
# ---------------------------------------------------------------------------

FR_CODE = "code"
FR_MESSAGE = "message"

# ---------------------------------------------------------------------------
# Pre-analysis command fields
# ---------------------------------------------------------------------------

PA_FIELD_ID = "id"
PA_FIELD_RUN = "run"
PA_FIELD_PURPOSE = "purpose"
PA_FIELD_FAIL_ON_NONZERO = "fail_on_nonzero"
PA_FIELD_OUTPUT_FILES = "output_files"
