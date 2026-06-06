"""Local token estimation.

The package is model-independent.  If ``tiktoken`` is installed it is used only
as a tokenizer implementation; no network or model call is made.  The fallback
is deterministic and dependency-free.
"""

from __future__ import annotations

import re

_CODE_OR_SHELL_RE = re.compile(r"[{}();]|\b(?:def|class|function|git|docker|kubectl|terraform|sudo|npm|python)\b")
_LOG_RE = re.compile(r"\b(?:traceback|error|exception|warn|info|debug|failed|panic)\b", re.IGNORECASE)


def _tiktoken_count(text: str) -> int | None:
    try:
        import tiktoken  # type: ignore
    except Exception:
        return None
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return None


def estimate_tokens(text: str) -> int:
    """Return a conservative local token estimate for text/code/logs."""

    if not text:
        return 0

    count = _tiktoken_count(text)
    if count is not None:
        return max(1, count)

    # General English approximation: ~4 chars/token.  Code/logs are denser and
    # often contain punctuation, paths, hashes, stack frames and flags, so use a
    # slightly higher estimate.
    length = len(text)
    multiplier = 1.0
    if _CODE_OR_SHELL_RE.search(text):
        multiplier += 0.15
    if _LOG_RE.search(text):
        multiplier += 0.15
    if "\n" in text and len(text.splitlines()) > 8:
        multiplier += 0.10
    return max(1, int((length / 4.0) * multiplier + 0.999))
