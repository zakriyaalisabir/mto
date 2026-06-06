from machine_shell_token_optimizer.classifier import InputClassifier


def test_shell_command_preserved_classification() -> None:
    c = InputClassifier().classify("git status")
    assert c.input_type == "git_instruction"
    assert c.risk_level == "low"
    assert c.should_optimize is False


def test_dangerous_command_high_risk() -> None:
    c = InputClassifier().classify("rm -rf ./build")
    assert c.input_type == "dangerous_command"
    assert c.risk_level == "high"
    assert c.should_optimize is False


def test_ai_prompt_classification() -> None:
    c = InputClassifier().classify("Please explain this stack trace and give me a fix command")
    assert c.should_optimize is True
    assert c.input_type in {"ai_prompt", "debugging_request", "log_or_traceback"}
