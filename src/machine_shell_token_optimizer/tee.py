"""Tee system: saves full command output to local files on failure."""

from __future__ import annotations

import time
from pathlib import Path

_MIN_SIZE = 500  # bytes — outputs shorter than this are not saved
_MAX_SIZE = 1_048_576  # 1MB — truncate above this


def tee_output(
    command_name: str,
    output: str,
    exit_code: int,
    *,
    tee_dir: str | None = None,
    mode: str = "failures",
    max_files: int = 20,
) -> str | None:
    """Save output to a tee file. Returns file path or None if skipped."""
    if mode == "never":
        return None
    if mode == "failures" and exit_code == 0:
        return None
    if len(output) < _MIN_SIZE:
        return None

    from .config import default_tee_dir
    directory = Path(tee_dir) if tee_dir else default_tee_dir()
    directory.mkdir(parents=True, exist_ok=True)

    # Truncate if too large
    content = output[:_MAX_SIZE]
    if len(output) > _MAX_SIZE:
        content += f"\n[truncated at {_MAX_SIZE} bytes]"

    # Write file
    timestamp = int(time.time())
    safe_name = command_name.replace("/", "_").replace(" ", "_")[:40]
    filename = f"{timestamp}_{safe_name}.log"
    filepath = directory / filename
    filepath.write_text(content, encoding="utf-8")

    # Rotate old files
    _rotate(directory, max_files)

    return str(filepath)


def _rotate(directory: Path, max_files: int) -> None:
    """Keep only the most recent max_files log files."""
    logs = sorted(directory.glob("*.log"), key=lambda p: p.stat().st_mtime)
    while len(logs) > max_files:
        logs.pop(0).unlink()
