"""Tests for optimization level behavior (conservative/moderate/aggressive)."""

from machine_shell_token_optimizer.middleware import ShellTokenOptimizer
from machine_shell_token_optimizer.models import OptimizationLevel


VERBOSE_INPUT = (
    "Please please can you help me fix this issue. "
    "I keep getting this error over and over again. "
    "I don't know what to do. "
    "Can you please explain what is wrong and give me the correct command to fix it. "
    "I really need help with this. "
    "Here is the error that I keep getting repeatedly. "
    "I want you to fix it for me please."
)


def test_aggressive_much_shorter_than_conservative(tmp_path) -> None:
    con = ShellTokenOptimizer(db_path=tmp_path / "c.db", level=OptimizationLevel.CONSERVATIVE)
    agg = ShellTokenOptimizer(db_path=tmp_path / "a.db", level=OptimizationLevel.AGGRESSIVE)
    try:
        r_con = con.process(VERBOSE_INPUT)
        r_agg = agg.process(VERBOSE_INPUT)
        assert r_agg.was_optimized
        assert r_agg.optimized_token_estimate < r_con.optimized_token_estimate
        assert r_agg.token_savings_percent > r_con.token_savings_percent
    finally:
        con.close()
        agg.close()


def test_aggressive_preserves_shell_commands(tmp_path) -> None:
    opt = ShellTokenOptimizer(db_path=tmp_path / "db.sqlite3", level=OptimizationLevel.AGGRESSIVE)
    try:
        result = opt.process("git push origin main")
        assert result.optimized_text == "git push origin main"
        assert result.was_optimized is False
    finally:
        opt.close()


def test_aggressive_preserves_code_blocks(tmp_path) -> None:
    text = '''Refactor this please please.
```python
def add(a, b):
    return a + b
```
'''
    opt = ShellTokenOptimizer(db_path=tmp_path / "db.sqlite3", level=OptimizationLevel.AGGRESSIVE)
    try:
        result = opt.process(text)
        assert "```python\ndef add(a, b):\n    return a + b\n```" in result.optimized_text
    finally:
        opt.close()


def test_aggressive_preserves_paths_and_errors(tmp_path) -> None:
    text = "I keep getting ValueError: bad config at /tmp/app.py line 4. Please please help me fix this error."
    opt = ShellTokenOptimizer(db_path=tmp_path / "db.sqlite3", level=OptimizationLevel.AGGRESSIVE)
    try:
        result = opt.process(text)
        assert "/tmp/app.py" in result.optimized_text
        assert "ValueError: bad config" in result.optimized_text
    finally:
        opt.close()


def test_moderate_removes_stop_phrases(tmp_path) -> None:
    text = "I don't know what to do. Fix the TypeError in main.py. Nothing works. Thanks in advance."
    opt = ShellTokenOptimizer(db_path=tmp_path / "db.sqlite3", level=OptimizationLevel.MODERATE)
    try:
        result = opt.process(text)
        assert result.was_optimized
        assert "don't know what to do" not in result.optimized_text.lower()
    finally:
        opt.close()


def test_clause_dedup_removes_repeated_intent(tmp_path) -> None:
    text = "Help me fix this error. I need you to fix this bug. Please fix this issue for me."
    opt = ShellTokenOptimizer(db_path=tmp_path / "db.sqlite3", level=OptimizationLevel.AGGRESSIVE)
    try:
        result = opt.process(text)
        assert result.was_optimized
        assert result.optimized_token_estimate < result.input_token_estimate
    finally:
        opt.close()
