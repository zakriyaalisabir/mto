"""Tests for the optional local model compressor integration."""

from unittest.mock import patch

from machine_shell_token_optimizer.compressor import is_available, model_status, compress
from machine_shell_token_optimizer.middleware import ShellTokenOptimizer
from machine_shell_token_optimizer.models import OptimizationLevel


def test_compressor_not_available_without_deps():
    """Without transformers/torch installed, compressor gracefully reports unavailable."""
    with patch("machine_shell_token_optimizer.compressor.is_available", return_value=False):
        from machine_shell_token_optimizer.compressor import compress as c
        assert c("hello world") is None


def test_model_status_without_deps():
    status = model_status()
    assert "model_name" in status
    assert "backend_available" in status
    # If transformers not installed, backend_available is False
    assert isinstance(status["backend_available"], bool)


def test_optimizer_works_without_model(tmp_path):
    """Even in aggressive mode, optimizer works fine when model is not available."""
    opt = ShellTokenOptimizer(db_path=tmp_path / "db.sqlite3", level=OptimizationLevel.AGGRESSIVE)
    try:
        result = opt.process("Please please help me fix this error over and over again.")
        assert result.was_optimized
        assert result.token_savings > 0
    finally:
        opt.close()


def test_compressor_used_when_available(tmp_path):
    """When model compress returns a shorter result, it becomes a candidate."""
    with patch("machine_shell_token_optimizer.optimizer._try_model_compress", return_value="Fix error."):
        opt = ShellTokenOptimizer(db_path=tmp_path / "db.sqlite3", level=OptimizationLevel.AGGRESSIVE)
        try:
            result = opt.process("Please please help me fix this error. I keep getting this error over and over.")
            assert result.was_optimized
            # Model result "Fix error." should win if it has the best score
            assert result.token_savings > 0
        finally:
            opt.close()


def test_compressor_rejected_if_drops_path(tmp_path):
    """Model result is rejected by semantic penalty if it drops critical paths."""
    with patch("machine_shell_token_optimizer.optimizer._try_model_compress", return_value="Fix this."):
        opt = ShellTokenOptimizer(db_path=tmp_path / "db.sqlite3", level=OptimizationLevel.AGGRESSIVE)
        try:
            # Input with a path that must be preserved
            result = opt.process("Please fix the error in /tmp/app/main.py line 42. Please help me fix this.")
            # The path must still be in the output (model result "Fix this." drops it)
            assert "/tmp/app/main.py" in result.optimized_text
        finally:
            opt.close()


def test_model_cli_status(tmp_path):
    """CLI model status subcommand runs without error."""
    import subprocess
    import sys
    import os
    env = os.environ.copy()
    env["PYTHONPATH"] = str(tmp_path.parents[3] / "src") if "src" in str(tmp_path) else ""
    # Use the installed module directly
    result = subprocess.run(
        [sys.executable, "-m", "machine_shell_token_optimizer.cli", "model", "status"],
        capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "model_name" in result.stdout
