"""Model-independent token optimization middleware used by shell integration."""

from __future__ import annotations

from pathlib import Path

from .classifier import InputClassifier
from .models import InputClassification, OptimizationLevel, OptimizationResult
from .optimizer import PromptOptimizer
from .redaction import redact_secrets
from .storage import ShellTokenStorage
from .tokenizer import estimate_tokens


class ShellTokenOptimizer:
    """Local, deterministic shell/prompt optimizer.

    The object is independent of any model or agent.  It classifies strings,
    optimizes only AI-bound text when explicitly asked, preserves shell commands,
    and logs redacted metadata to SQLite.
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        enabled: bool = True,
        storage: ShellTokenStorage | None = None,
        classifier: InputClassifier | None = None,
        optimizer: PromptOptimizer | None = None,
        log_to_sqlite: bool = True,
        min_score: float = 0.0,
        level: OptimizationLevel = OptimizationLevel.CONSERVATIVE,
    ) -> None:
        self.enabled = enabled
        self.level = level
        self.classifier = classifier or InputClassifier()
        self.optimizer = optimizer or PromptOptimizer(level=level)
        self.log_to_sqlite = log_to_sqlite
        self.min_score = min_score
        self.storage = storage if storage is not None else ShellTokenStorage(db_path)

    def classify_input(self, text: str) -> InputClassification:
        return self.classifier.classify(text)

    def estimate_tokens(self, text: str) -> int:
        return estimate_tokens(text)

    def redact_secrets(self, text: str) -> str:
        return redact_secrets(text)

    def optimize_input(self, text: str, classification: InputClassification) -> OptimizationResult:
        input_tokens = estimate_tokens(text)
        if not self.enabled:
            return self._build_result(
                original_text=text,
                optimized_text=text,
                classification=classification,
                input_tokens=input_tokens,
                was_optimized=False,
                reason="optimizer disabled",
                score=0.0,
            )
        historical_bonus = self.storage.historical_success_bonus(classification.input_type)
        optimized, was_optimized, reason, score = self.optimizer.optimize(
            text,
            classification,
            historical_success_bonus=historical_bonus,
            min_score=self.min_score,
        )
        return self._build_result(
            original_text=text,
            optimized_text=optimized,
            classification=classification,
            input_tokens=input_tokens,
            was_optimized=was_optimized,
            reason=reason,
            score=score,
        )

    def process(self, text: str, command_name: str | None = None) -> OptimizationResult:
        classification = self.classify_input(text)
        result = self.optimize_input(text, classification)
        result.command_name = command_name
        if classification.input_type == "dangerous_command" and classification.risk_level == "high":
            result.status = "high_risk_unmodified"
        if self.log_to_sqlite:
            self.log_optimization_run(result)
        return result

    def log_optimization_run(self, result: OptimizationResult) -> str:
        if not self.log_to_sqlite:
            return result.run_id or ""
        return self.storage.log_optimization_run(result)

    def feedback(self, run_id: str, rating: str, notes: str = "") -> str:
        return self.storage.record_feedback(run_id, rating, notes)

    def stats(self) -> dict[str, object]:
        return self.storage.stats()

    def dry_run(self, text: str, command_name: str | None = None) -> dict[str, object]:
        result = self.process(text, command_name=command_name)
        return {
            "original_input": result.original_text,
            "classified_type": result.input_type,
            "risk_level": result.risk_level,
            "input_token_estimate": result.input_token_estimate,
            "optimized_token_estimate": result.optimized_token_estimate,
            "estimated_savings": result.token_savings,
            "estimated_savings_percent": result.token_savings_percent,
            "was_optimized": result.was_optimized,
            "reason": result.reason,
            "optimized_output": result.optimized_text,
            "run_id": result.run_id,
        }

    def close(self) -> None:
        self.storage.close()

    def _build_result(
        self,
        *,
        original_text: str,
        optimized_text: str,
        classification: InputClassification,
        input_tokens: int,
        was_optimized: bool,
        reason: str,
        score: float,
    ) -> OptimizationResult:
        optimized_tokens = estimate_tokens(optimized_text)
        savings = input_tokens - optimized_tokens
        savings_percent = (savings / input_tokens * 100.0) if input_tokens else 0.0
        return OptimizationResult(
            original_text=original_text,
            optimized_text=optimized_text,
            input_type=classification.input_type,
            risk_level=classification.risk_level,
            was_optimized=was_optimized,
            input_token_estimate=input_tokens,
            optimized_token_estimate=optimized_tokens,
            token_savings=savings,
            token_savings_percent=savings_percent,
            reason=reason,
            optimization_score=score,
            debug={"classification_reason": classification.reason, **classification.metadata},
        )


# Backward-friendly alias for callers that still import the previous name.
TokenOptimizationMiddleware = ShellTokenOptimizer
