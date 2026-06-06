from machine_shell_token_optimizer.redaction import redact_secrets
from machine_shell_token_optimizer import ShellTokenOptimizer
from machine_shell_token_optimizer.storage import ShellTokenStorage


def test_secret_redaction():
    redacted = redact_secrets("export OPENAI_API_KEY=sk-1234567890abcdef1234567890abcdef")
    assert "sk-123" not in redacted
    assert "[REDACTED" in redacted or "[REDACTED]" in redacted


def test_sqlite_logging_redacts_secret(tmp_path):
    db = tmp_path / "db.sqlite3"
    opt = ShellTokenOptimizer(db_path=db)
    try:
        result = opt.process("Please explain this token sk-1234567890abcdef1234567890abcdef and summarize")
        assert result.run_id is not None
    finally:
        opt.close()
    storage = ShellTokenStorage(db)
    try:
        row = storage.connection.execute("SELECT input_preview FROM optimization_runs LIMIT 1").fetchone()
        assert row is not None
        assert "sk-123" not in row["input_preview"]
    finally:
        storage.close()


def test_feedback_updates_pattern_score(tmp_path):
    db = tmp_path / "db.sqlite3"
    opt = ShellTokenOptimizer(db_path=db)
    try:
        result = opt.process("Please please help me fix this issue. " * 8)
        assert result.run_id
        opt.feedback(result.run_id, "good", "useful")
        rows = opt.storage.connection.execute("SELECT success_score FROM optimization_patterns").fetchall()
        assert any(float(row["success_score"]) > 0 for row in rows)
    finally:
        opt.close()
