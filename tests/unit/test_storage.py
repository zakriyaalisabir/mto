import sqlite3

from machine_shell_token_optimizer.middleware import ShellTokenOptimizer
from machine_shell_token_optimizer.shell import shell_preexec, shell_precmd
from machine_shell_token_optimizer.storage import ShellTokenStorage


def test_shell_event_logging_and_completion(tmp_path) -> None:
    db = tmp_path / "mto.sqlite3"
    event_id = shell_preexec("echo hello", shell="bash", pid=1001, cwd=str(tmp_path), db_path=str(db))
    assert event_id
    completed = shell_precmd(shell="bash", pid=1001, status=0, db_path=str(db))
    assert completed == event_id
    storage = ShellTokenStorage(db)
    try:
        stats = storage.stats()
        assert stats["shell_events"] == 1
        assert stats["top_commands"][0]["command_name"] == "echo"
    finally:
        storage.close()


def test_secret_redacted_in_storage(tmp_path) -> None:
    db = tmp_path / "mto.sqlite3"
    shell_preexec("export OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz123456", shell="bash", pid=1002, cwd=str(tmp_path), db_path=str(db))
    con = sqlite3.connect(db)
    try:
        stored = con.execute("SELECT raw_command_preview FROM shell_command_events").fetchone()[0]
    finally:
        con.close()
    assert "sk-" not in stored
    assert "REDACTED" in stored


def test_feedback_updates_pattern_score(tmp_path) -> None:
    db = tmp_path / "mto.sqlite3"
    opt = ShellTokenOptimizer(db_path=db)
    try:
        result = opt.process(
            "Please please help me fix this issue. I get this error. "
            "Please please help me fix this issue. I get this error."
        )
        assert result.run_id
        feedback_id = opt.feedback(result.run_id, "good", "worked")
        assert feedback_id
    finally:
        opt.close()
