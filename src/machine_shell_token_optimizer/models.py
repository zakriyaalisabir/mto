"""Public dataclasses used by the shell-native token optimizer."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class OptimizationLevel(str, Enum):
    """How aggressively to compress AI-bound text."""

    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


@dataclass(slots=True)
class InputClassification:
    """Classification result for a command line, prompt, log, or mixed input."""

    input_type: str
    risk_level: str
    should_optimize: bool
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OptimizationResult:
    """Result returned by the local optimizer."""

    original_text: str
    optimized_text: str
    input_type: str
    risk_level: str
    was_optimized: bool
    input_token_estimate: int
    optimized_token_estimate: int
    token_savings: int
    token_savings_percent: float
    reason: str
    run_id: str | None = None
    optimization_score: float = 0.0
    command_name: str | None = None
    status: str = "ok"
    debug: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ShellCommandEvent:
    """A shell-level command observation event."""

    id: str
    shell: str
    pid: int
    cwd: str
    raw_command: str
    input_type: str
    risk_level: str
    token_estimate: int
    was_modified: bool = False
    optimized_preview: str = ""
    exit_code: int | None = None
    status: str = "started"
    notes: str | None = None


@dataclass(slots=True)
class ShellConfig:
    """Runtime configuration stored as JSON under ~/.config/mto/config.json."""

    enabled: bool = True
    observe_all_commands: bool = True
    db_path: str | None = None
    wrap_commands: list[str] = field(default_factory=list)
    optimize_commands: dict[str, str] = field(default_factory=dict)
    store_full_text: bool = False
    default_timeout_seconds: float = 300.0
    optimization_level: str = "aggressive"
    # Retention
    history_days: int = 90
    # Tee system
    tee_enabled: bool = True
    tee_mode: str = "failures"  # "failures", "always", "never"
    tee_max_files: int = 20
    tee_dir: str | None = None
    # Hooks
    exclude_commands: list[str] = field(default_factory=list)
    # Per-project filters
    project_filters_file: str = ".mto/filters.json"
