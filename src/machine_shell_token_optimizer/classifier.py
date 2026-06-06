"""Conservative shell/prompt classifier.

The classifier is intentionally deterministic and local.  It never calls an LLM
or any external service.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

from .models import InputClassification

DANGEROUS_COMMAND_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\brm\s+(-[A-Za-z]*r[A-Za-z]*f|-rf|-fr)\b",
        r"^\s*sudo\b",
        r"\bchmod\s+-R\b",
        r"\bchown\s+-R\b",
        r"\bdd\s+.*\bof\s*=",
        r"\bmkfs(?:\.[a-z0-9]+)?\b",
        r"\bcurl\b[\s\S]*\|\s*(?:sudo\s+)?(?:ba)?sh\b",
        r"\bwget\b[\s\S]*\|\s*(?:sudo\s+)?(?:ba)?sh\b",
        r"\bkubectl\s+delete\b",
        r"\bterraform\s+destroy\b",
        r"\bdocker\s+system\s+prune\b",
        r"\bgit\s+reset\s+--hard\b",
        r"\bgit\s+clean\s+-[a-z]*f[a-z]*d?[a-z]*\b",
        r"\bDROP\s+(?:DATABASE|TABLE|SCHEMA)\b",
    ]
)

SHELL_COMMAND_PREFIXES: set[str] = {
    "alias",
    "awk",
    "bash",
    "cat",
    "cd",
    "chmod",
    "chown",
    "cp",
    "curl",
    "docker",
    "echo",
    "env",
    "export",
    "find",
    "git",
    "grep",
    "head",
    "history",
    "jq",
    "kubectl",
    "less",
    "ln",
    "ls",
    "make",
    "mkdir",
    "mv",
    "node",
    "npm",
    "npx",
    "pip",
    "pipx",
    "pnpm",
    "python",
    "python3",
    "rm",
    "sed",
    "sh",
    "ssh",
    "sudo",
    "tail",
    "tee",
    "terraform",
    "touch",
    "tree",
    "uv",
    "vim",
    "vi",
    "wget",
    "yarn",
    "zsh",
}

GIT_SUBCOMMANDS_RAW = {
    "status",
    "diff",
    "log",
    "show",
    "branch",
    "checkout",
    "switch",
    "add",
    "commit",
    "pull",
    "push",
    "fetch",
    "rebase",
    "merge",
    "stash",
    "reset",
    "clean",
}

AI_PROMPT_MARKERS: tuple[str, ...] = (
    "explain",
    "summarize",
    "summarise",
    "optimise",
    "optimize",
    "refactor",
    "write code",
    "create",
    "generate",
    "fix this",
    "fix the",
    "debug",
    "diagnose",
    "what is wrong",
    "help me",
    "please",
    "implement",
    "review",
    "convert",
    "rewrite",
    "give me",
    "how do i",
)

CODE_INSTRUCTION_MARKERS: tuple[str, ...] = (
    "refactor",
    "write code",
    "implement",
    "function",
    "class",
    "module",
    "unit test",
    "pytest",
    "typescript",
    "python",
    "javascript",
    "golang",
    "terraform module",
    "cloudformation",
)

DEBUG_MARKERS: tuple[str, ...] = (
    "traceback (most recent call last):",
    "stack trace",
    "exception",
    "error:",
    "failed",
    "panic:",
    "segmentation fault",
    "syntaxerror",
    "typeerror",
    "valueerror",
)

_CODE_FENCE_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_LOG_LINE_RE = re.compile(
    r"^\s*(?:\[?\d{4}-\d{2}-\d{2}|ERROR\b|WARN(?:ING)?\b|INFO\b|DEBUG\b|TRACE\b|CRITICAL\b|FATAL\b)",
    re.IGNORECASE,
)
_FILE_PATH_RE = re.compile(r"(?:^|\s)(?:/[\w./:@+-]+|[A-Za-z]:\\[^\s:]+|[\w.-]+/[\w./:@+-]+)(?::\d+)?")
_INLINE_COMMAND_RE = re.compile(r"(?:^|\s)(?:`[^`]+`|\$\s+\w+|(?:git|docker|kubectl|terraform|npm|python3?)\s+[-\w])")


@dataclass(slots=True)
class InputClassifier:
    """Heuristic classifier used by shell hooks and optimizers."""

    known_shell_prefixes: set[str] | None = None

    def classify(self, text: str) -> InputClassification:
        normalized = text.strip()
        lower = normalized.lower()

        if not normalized:
            return InputClassification("ai_prompt", "low", False, "empty input")

        dangerous = self._dangerous_match(normalized)
        shell_like = self._looks_like_shell_command(normalized)

        if dangerous and (shell_like or self._looks_like_sql_or_command(normalized)):
            return InputClassification(
                "dangerous_command",
                "high",
                False,
                f"dangerous command pattern detected: {dangerous.pattern}",
            )

        if shell_like:
            command_type = self._shell_command_type(normalized)
            risk = "medium" if self._moderate_risk_shell(normalized) else "low"
            return InputClassification(
                command_type,
                risk,
                False,
                "shell command detected; preserve unchanged",
                metadata={"shell_like": True},
            )

        has_fence = bool(_CODE_FENCE_RE.search(normalized))
        has_debug = any(marker in lower for marker in DEBUG_MARKERS)
        has_ai_marker = any(marker in lower for marker in AI_PROMPT_MARKERS)
        has_code_marker = any(marker in lower for marker in CODE_INSTRUCTION_MARKERS)
        has_logs = self._looks_like_logs(normalized)
        has_paths = bool(_FILE_PATH_RE.search(normalized))
        has_inline_command = bool(_INLINE_COMMAND_RE.search(normalized))

        if has_debug and ("traceback" in lower or has_logs):
            return InputClassification(
                "log_or_traceback" if not has_ai_marker else "debugging_request",
                "medium" if has_paths else "low",
                True,
                "debug/log/traceback context detected",
                metadata={"has_paths": has_paths},
            )

        if has_fence and (has_ai_marker or has_code_marker):
            return InputClassification(
                "mixed_input",
                "medium",
                True,
                "prompt contains protected code/command block plus prose",
                metadata={"has_code_fence": True},
            )

        if has_logs:
            return InputClassification("log_or_traceback", "low", True, "log-like input detected")

        if has_code_marker or has_fence:
            return InputClassification(
                "code_instruction",
                "medium" if has_fence else "low",
                True,
                "code-related instruction detected",
                metadata={"has_code_fence": has_fence},
            )

        if has_inline_command and has_ai_marker:
            return InputClassification(
                "mixed_input",
                "medium",
                True,
                "natural language contains inline command; optimize prose conservatively",
            )

        if has_ai_marker or self._looks_like_question_or_instruction(normalized):
            return InputClassification("ai_prompt", "low", True, "natural-language instruction detected")

        return InputClassification(
            "ai_prompt",
            "low",
            True,
            "not shell-like; treat as AI-bound text if passed to optimizer",
        )

    def _prefixes(self) -> set[str]:
        return self.known_shell_prefixes or SHELL_COMMAND_PREFIXES

    def _dangerous_match(self, text: str) -> re.Pattern[str] | None:
        for pattern in DANGEROUS_COMMAND_PATTERNS:
            if pattern.search(text):
                return pattern
        return None

    def _looks_like_shell_command(self, text: str) -> bool:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) > 1:
            # Multiple shell lines are considered command text only if every line
            # is command-like and the block does not read like a prose request.
            lower = text.lower()
            if any(marker in lower for marker in AI_PROMPT_MARKERS):
                return False
            return all(self._single_line_shell_like(line) for line in lines)
        return self._single_line_shell_like(text)

    def _single_line_shell_like(self, line: str) -> bool:
        if not line:
            return False
        if line.startswith(("$ ", "# ")):
            line = line[2:].strip()

        # Pipelines and command chains are shell-like if their first command is shell-like.
        first_segment = re.split(r"\s*(?:&&|\|\||\||;)\s*", line, maxsplit=1)[0].strip()
        if not first_segment:
            return False

        try:
            parts = shlex.split(first_segment, posix=True)
        except ValueError:
            parts = first_segment.split()
        if not parts:
            return False

        first = parts[0]
        if first in {"time", "command", "builtin", "noglob"} and len(parts) > 1:
            first = parts[1]

        if first in self._prefixes():
            return True
        if first.startswith(("./", "../", "/")):
            return True
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", first) and len(parts) > 1:
            next_cmd = parts[1]
            return next_cmd in self._prefixes() or next_cmd.startswith(("./", "../", "/"))
        return False

    def _shell_command_type(self, text: str) -> str:
        try:
            parts = shlex.split(text.strip(), posix=True)
        except ValueError:
            parts = text.strip().split()
        if not parts:
            return "raw_shell_command"
        first = parts[0]
        if first == "git":
            return "git_instruction"
        if first in {"rm", "mv", "cp", "mkdir", "touch", "chmod", "chown", "find", "ls", "cd"}:
            return "filesystem_instruction"
        return "raw_shell_command"

    def _moderate_risk_shell(self, text: str) -> bool:
        return bool(re.search(r"\b(?:rm|mv|chmod|chown|kubectl|terraform|docker|git\s+reset|git\s+clean)\b", text))

    def _looks_like_sql_or_command(self, text: str) -> bool:
        return bool(re.search(r"\bDROP\s+(?:DATABASE|TABLE|SCHEMA)\b", text, re.IGNORECASE))

    def _looks_like_logs(self, text: str) -> bool:
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            return False
        log_like = sum(1 for line in lines if _LOG_LINE_RE.search(line))
        return log_like >= max(2, len(lines) // 3)

    def _looks_like_question_or_instruction(self, text: str) -> bool:
        lower = text.lower()
        if text.endswith("?"):
            return True
        if re.match(r"^(?:please\s+)?(?:explain|summarize|summarise|create|write|fix|debug|diagnose|review|convert|rewrite|implement)\b", lower):
            return True
        if len(text.split()) >= 6 and not self._single_line_shell_like(text):
            return True
        return False
