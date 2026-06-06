from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
SRC = PROJECT / "src"


def _env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    env["MTO_DB_PATH"] = str(tmp_path / "mto.sqlite3")
    return env


def _mto_cmd() -> list[str]:
    return [sys.executable, "-m", "machine_shell_token_optimizer.cli"]


def test_cli_classify_and_exec_dry_run(tmp_path) -> None:
    env = _env(tmp_path)
    classified = subprocess.run(
        _mto_cmd() + ["classify", "rm -rf ./build", "--json"],
        cwd=PROJECT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    data = json.loads(classified.stdout)
    assert data["input_type"] == "dangerous_command"
    assert data["risk_level"] == "high"

    dry = subprocess.run(
        _mto_cmd() + ["exec", "--dry-run", "--", "echo", "hello"],
        cwd=PROJECT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "effective_argv" in dry.stdout


def test_install_uninstall_shell_hook_on_temp_rcfile(tmp_path) -> None:
    env = _env(tmp_path)
    rc = tmp_path / ".bashrc"
    rc.write_text("# existing\n", encoding="utf-8")
    subprocess.run(
        _mto_cmd() + ["install-shell", "--shell", "bash", "--rcfile", str(rc)],
        cwd=PROJECT,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )
    text = rc.read_text(encoding="utf-8")
    assert "# >>> mto shell integration >>>" in text
    subprocess.run(
        _mto_cmd() + ["uninstall-shell", "--shell", "bash", "--rcfile", str(rc)],
        cwd=PROJECT,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )
    assert "# >>> mto shell integration >>>" not in rc.read_text(encoding="utf-8")
    assert "# existing" in rc.read_text(encoding="utf-8")


def test_bash_hook_observes_and_unmounts(tmp_path) -> None:
    if shutil.which("bash") is None:
        return
    env = _env(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    mto = bin_dir / "mto"
    mto.write_text(
        f"#!/bin/sh\nPYTHONPATH={SRC} MTO_DB_PATH={env['MTO_DB_PATH']} exec {sys.executable} -m machine_shell_token_optimizer.cli \"$@\"\n",
        encoding="utf-8",
    )
    mto.chmod(0o755)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    script = '''
eval "$(mto shell-hook bash)"
echo observed >/dev/null
__mto_precmd
mto_unmount
echo unobserved >/dev/null
'''
    subprocess.run(["bash", "--noprofile", "--norc", "-c", script], env=env, text=True, capture_output=True, check=True)

    con = sqlite3.connect(env["MTO_DB_PATH"])
    try:
        commands = [row[0] for row in con.execute("SELECT raw_command_preview FROM shell_command_events ORDER BY created_at").fetchall()]
    finally:
        con.close()
    assert any("echo observed" in cmd for cmd in commands)
    assert not any("echo unobserved" in cmd for cmd in commands)
