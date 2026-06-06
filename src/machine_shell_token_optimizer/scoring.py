"""Local scoring for deciding whether an optimization is safe enough."""

from __future__ import annotations


def optimization_score(
    token_savings_percent: float,
    semantic_risk_penalty: float,
    historical_success_bonus: float = 0.0,
) -> float:
    return token_savings_percent - semantic_risk_penalty + historical_success_bonus
