from machine_shell_token_optimizer.middleware import ShellTokenOptimizer


def test_raw_shell_command_not_modified(tmp_path) -> None:
    opt = ShellTokenOptimizer(db_path=tmp_path / "db.sqlite3")
    try:
        result = opt.process("git status")
        assert result.optimized_text == "git status"
        assert result.was_optimized is False
        assert result.input_type == "git_instruction"
    finally:
        opt.close()


def test_repeated_prompt_is_compressed(tmp_path) -> None:
    text = (
        "Please please help me fix this issue. I get this error. "
        "Please please help me fix this issue. I get this error. "
        "Please explain what is wrong and give me the command."
    )
    opt = ShellTokenOptimizer(db_path=tmp_path / "db.sqlite3")
    try:
        result = opt.process(text)
        assert result.was_optimized is True
        assert result.token_savings > 0
        assert len(result.optimized_text) < len(text)
    finally:
        opt.close()


def test_traceback_final_error_and_path_preserved(tmp_path) -> None:
    tb = '''Please debug this.
Traceback (most recent call last):
  File "/tmp/app/main.py", line 4, in <module>
    run()
ValueError: bad config

Traceback (most recent call last):
  File "/tmp/app/main.py", line 4, in <module>
    run()
ValueError: bad config
'''
    opt = ShellTokenOptimizer(db_path=tmp_path / "db.sqlite3")
    try:
        result = opt.process(tb)
        assert "/tmp/app/main.py" in result.optimized_text
        assert "ValueError: bad config" in result.optimized_text
        assert result.token_savings >= 0
    finally:
        opt.close()


def test_code_block_preserved(tmp_path) -> None:
    text = '''Refactor this Python code. Keep behavior the same.
```python
def add(a, b):
    return a + b
```
Please please refactor this Python code. Keep behavior the same.
'''
    opt = ShellTokenOptimizer(db_path=tmp_path / "db.sqlite3")
    try:
        result = opt.process(text)
        assert "```python\ndef add(a, b):\n    return a + b\n```" in result.optimized_text
    finally:
        opt.close()
