"""Secret redaction for shell command logs and optimization history."""

from __future__ import annotations

import re

_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, flags), replacement)
    for pattern, flags, replacement in [
        (r"AKIA[0-9A-Z]{16}", 0, "[REDACTED_AWS_ACCESS_KEY]"),
        (r"ASIA[0-9A-Z]{16}", 0, "[REDACTED_AWS_TEMP_KEY]"),
        (r"(?i)aws_secret_access_key\s*=\s*[^\s]+", 0, "aws_secret_access_key=[REDACTED]"),
        (r"ghp_[A-Za-z0-9_]{20,}", 0, "[REDACTED_GITHUB_TOKEN]"),
        (r"github_pat_[A-Za-z0-9_]{20,}", 0, "[REDACTED_GITHUB_TOKEN]"),
        (r"sk-[A-Za-z0-9]{20,}", 0, "[REDACTED_OPENAI_KEY]"),
        (r"(?i)bearer\s+[A-Za-z0-9._\-+/=]{16,}", 0, "Bearer [REDACTED]"),
        (r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----", 0, "[REDACTED_PRIVATE_KEY]"),
        (r"(?m)^([A-Za-z_][A-Za-z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASS|PWD)\s*=\s*).+$", 0, r"\1[REDACTED]"),
        (r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", 0, "[REDACTED_JWT]"),
        (r"(?i)(api[_-]?key|access[_-]?token|secret|password)(\s*[:=]\s*)['\"]?[A-Za-z0-9._\-+/=]{12,}['\"]?", 0, r"\1\2[REDACTED]"),
    ]
)


def redact_secrets(text: str) -> str:
    """Return ``text`` with common secret forms replaced by placeholders."""

    redacted = text
    for pattern, replacement in _SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted
