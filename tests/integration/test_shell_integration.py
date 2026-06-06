from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from machine_shell_token_optimizer.shell import (
    BEGIN_MARKER,
    END_MARKER,
    generate_shell_hook,
    install_shell_hook,
    shell_precmd,
    shell_preexec,
    uninstall_shell_hook,
)
from machine_shell_token_optimizer.storage import ShellTokenStorage


def test_install_and_uninstall_shell_hook(tmp_path):
    rc = tmp_path / ".bashrc"
    rc.write_text("# existing\n", encoding="utf-8")
    install_shell_hook("bash", rc, wrap_commands=["fakeai"])
    text = rc.read_text(encoding="utf-8")
    assert BEGIN_MARKER in text
    assert END_MARKER in text
    assert "mto shell-hook bash" in text
    uninstall_shell_hook("bash", rc)
    text = rc.read_text(encoding="utf-8")
    assert BEGIN_MARKER not in text
    assert END_MARKER not in text
    assert "# existing" in text


def test_shell_preexec_and_precmd_log_event(tmp_path, monkeypatch):
    db = tmp_path / "db.sqlite3"
    monkeypatch.setenv("MTO_DB_PATH", str(db))
    event_id = shell_preexec("git status", shell="bash", pid=12345, cwd=str(tmp_path))
    assert event_id
    completed = shell_precmd(shell="bash", pid=12345, status=0)
    assert completed == event_id
    storage = ShellTokenStorage(db)
    try:
        row = storage.connection.execute("SELECT raw_command_preview, input_type, exit_code FROM shell_command_events").fetchone()
        assert row["raw_command_preview"] == "git status"
        assert row["input_type"] == "git_instruction"
        assert row["exit_code"] == 0
    finally:
        storage.close()


def test_cli_exec_dry_run_optimizes_payload(tmp_path):
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    env["MTO_DB_PATH"] = str(tmp_path / "db.sqlite3")
    cmd = [
        sys.executable,
        "-m",
        "machine_shell_token_optimizer.cli",
        "exec",
        "--optimize",
        "--dry-run",
        "--",
        "cat",
        "Please please help me fix this issue. " * 8,
    ]
    completed = subprocess.run(cmd, env=env, text=True, capture_output=True, check=True)
    data = json.loads(completed.stdout)
    assert data["optimized"] is True
    assert data["optimization"]["token_savings"] > 0
    assert len(data["optimization"]["optimized_text"]) < len("Please please help me fix this issue. " * 8)


def test_generated_bash_hook_contains_observer_and_wrapper():
    hook = generate_shell_hook("bash", wrap_commands=["fakeai"])
    assert "trap '__mto_preexec' DEBUG" in hook
    assert "__mto_precmd" in hook
    assert "MTO_WRAP_COMMANDS" in hook
    assert "mto exec --" in hook


def test_generated_bash_hook_observes_real_subshell_commands(tmp_path):
    root = Path(__file__).resolve().parents[2]
    db = tmp_path / "hook.sqlite3"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    mto_script = bin_dir / "mto"
    mto_script.write_text(
        f"#! /usr/bin/env bash\nPYTHONPATH={root / 'src'} exec {sys.executable} -m machine_shell_token_optimizer.cli \"$@\"\n",
        encoding="utf-8",
    )
    mto_script.chmod(0o755)
    script = f'''
set -e
export PATH="{bin_dir}:$PATH"
export PYTHONPATH="{root / 'src'}"
export MTO_DB_PATH="{db}"
eval "$(mto shell-hook bash)"
echo hello-mto >/dev/null
mto_unmount
echo after-unmount >/dev/null
'''
    completed = subprocess.run(["bash", "-lc", script], text=True, capture_output=True, timeout=20)
    assert completed.returncode == 0, completed.stderr
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute("SELECT raw_command_preview FROM shell_command_events").fetchall()
    finally:
        conn.close()
    commands = [row[0] for row in rows]
    assert any("echo hello-mto" in cmd for cmd in commands)
    assert not any("echo after-unmount" in cmd for cmd in commands)
