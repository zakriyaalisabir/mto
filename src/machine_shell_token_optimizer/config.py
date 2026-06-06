"""JSON config helpers for the shell-native tool."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import ShellConfig
from .storage import default_db_path


def default_config_path() -> Path:
    return Path.home() / ".config" / "mto" / "config.json"


def default_tee_dir() -> Path:
    return Path.home() / ".local" / "share" / "mto" / "tee"


def default_config() -> ShellConfig:
    return ShellConfig(
        enabled=True,
        observe_all_commands=True,
        db_path=str(default_db_path()),
        wrap_commands=[],
        optimize_commands={
            "codex": "argv_join",
            "cairo": "argv_join",
            "aider": "argv_join",
            "claude": "argv_join",
            "llm": "argv_join",
            "sgpt": "argv_join",
        },
        store_full_text=False,
        default_timeout_seconds=300.0,
        optimization_level="aggressive",
        history_days=90,
        tee_enabled=True,
        tee_mode="failures",
        tee_max_files=20,
        tee_dir=str(default_tee_dir()),
        exclude_commands=[],
        project_filters_file=".mto/filters.json",
    )


def is_disabled() -> bool:
    """Check if MTO_DISABLED=1 is set (skip optimization for this invocation)."""
    return os.environ.get("MTO_DISABLED", "").strip() in {"1", "true", "yes"}


def load_config(path: str | Path | None = None) -> ShellConfig:
    config_path = Path(path).expanduser() if path else default_config_path()
    cfg = default_config()
    if config_path.exists():
        data = json.loads(config_path.read_text(encoding="utf-8"))
        cfg = _merge_config(cfg, data)

    # Load per-project filters if present
    project_filters = Path.cwd() / cfg.project_filters_file
    if project_filters.exists():
        try:
            proj = json.loads(project_filters.read_text(encoding="utf-8"))
            if "exclude_commands" in proj:
                cfg.exclude_commands = list(set(cfg.exclude_commands + proj["exclude_commands"]))
        except (json.JSONDecodeError, KeyError):
            pass

    # Environment overrides
    if os.environ.get("MTO_DB_PATH"):
        cfg.db_path = os.environ["MTO_DB_PATH"]
    if os.environ.get("MTO_ENABLED") is not None:
        cfg.enabled = os.environ["MTO_ENABLED"].strip().lower() not in {"0", "false", "no", "off"}
    if os.environ.get("MTO_OBSERVE_ALL") is not None:
        cfg.observe_all_commands = os.environ["MTO_OBSERVE_ALL"].strip().lower() not in {"0", "false", "no", "off"}
    if os.environ.get("MTO_WRAP_COMMANDS"):
        cfg.wrap_commands = _split_commands(os.environ["MTO_WRAP_COMMANDS"])
    if os.environ.get("MTO_OPTIMIZATION_LEVEL"):
        cfg.optimization_level = os.environ["MTO_OPTIMIZATION_LEVEL"].strip().lower()
    if os.environ.get("MTO_TEE_DIR"):
        cfg.tee_dir = os.environ["MTO_TEE_DIR"]
    if is_disabled():
        cfg.enabled = False
    return cfg


def write_default_config(path: str | Path | None = None, *, force: bool = False) -> Path:
    config_path = Path(path).expanduser() if path else default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.exists() and not force:
        return config_path
    config_path.write_text(json.dumps(asdict(default_config()), indent=2) + "\n", encoding="utf-8")
    return config_path


def _merge_config(base: ShellConfig, data: dict[str, Any]) -> ShellConfig:
    if "enabled" in data:
        base.enabled = bool(data["enabled"])
    if "observe_all_commands" in data:
        base.observe_all_commands = bool(data["observe_all_commands"])
    if "db_path" in data and data["db_path"]:
        base.db_path = str(data["db_path"])
    if "wrap_commands" in data:
        base.wrap_commands = list(map(str, data.get("wrap_commands") or []))
    if "optimize_commands" in data:
        base.optimize_commands = {str(k): str(v) for k, v in dict(data.get("optimize_commands") or {}).items()}
    if "store_full_text" in data:
        base.store_full_text = bool(data["store_full_text"])
    if "default_timeout_seconds" in data:
        base.default_timeout_seconds = float(data["default_timeout_seconds"])
    if "optimization_level" in data:
        base.optimization_level = str(data["optimization_level"]).lower()
    if "history_days" in data:
        base.history_days = int(data["history_days"])
    if "tee_enabled" in data:
        base.tee_enabled = bool(data["tee_enabled"])
    if "tee_mode" in data:
        base.tee_mode = str(data["tee_mode"])
    if "tee_max_files" in data:
        base.tee_max_files = int(data["tee_max_files"])
    if "tee_dir" in data and data["tee_dir"]:
        base.tee_dir = str(data["tee_dir"])
    if "exclude_commands" in data:
        base.exclude_commands = list(map(str, data.get("exclude_commands") or []))
    if "project_filters_file" in data:
        base.project_filters_file = str(data["project_filters_file"])
    return base


def _split_commands(value: str) -> list[str]:
    return [item.strip() for item in value.replace(",", " ").split() if item.strip()]
