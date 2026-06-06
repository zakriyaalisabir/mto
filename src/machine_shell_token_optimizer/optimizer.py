"""Deterministic local prompt/log optimizer.

This module is model-independent. It does not call an LLM. It only applies
conservative local transformations when the classifier says optimization is safe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .classifier import InputClassifier
from .models import InputClassification, OptimizationLevel, OptimizationResult
from .scoring import optimization_score
from .tokenizer import estimate_tokens

_CODE_FENCE_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_TRACEBACK_START_RE = re.compile(r"Traceback \(most recent call last\):")
_FINAL_ERROR_RE = re.compile(r"(?:[A-Za-z_][\w.]*Error|[A-Za-z_][\w.]*Exception|Exception|Error)\s*:\s*.*|panic:\s*.*|segmentation fault.*", re.IGNORECASE)
_PATH_RE = re.compile(r"(?:/[^\s:]+|[A-Za-z]:\\[^\s:]+|[\w.-]+/[\w./@:+-]+)(?::\d+)?")
_SHELL_LINE_RE = re.compile(r"^\s*(?:\$\s*)?(?:git|docker|kubectl|terraform|npm|pnpm|yarn|python3?|pip|uv|bash|zsh|sh|sudo|rm|mv|cp|mkdir|chmod|chown|curl|wget)\b")
_LOG_LINE_RE = re.compile(r"^\s*(?:\[?\d{4}-\d{2}-\d{2}|ERROR\b|WARN(?:ING)?\b|INFO\b|DEBUG\b|TRACE\b|CRITICAL\b|FATAL\b)", re.IGNORECASE)

# --- Filler patterns by level ---

_FILLER_CONSERVATIVE: list[tuple[str, str]] = [
    (r"\bplease\s+please\b", "please"),
    (r"\bcan you(?: please)?\b", ""),
    (r"\bcould you(?: please)?\b", ""),
    (r"\bwould you(?: please)?\b", ""),
    (r"\bi really\b", "I"),
    (r"\bi do not know what to do\.?", ""),
    (r"\bi don't know what to do\.?", ""),
    (r"\bi keep getting\b", "I get"),
    (r"\bi want you to\b", "Please"),
    (r"\bhere is the\b", ""),
    (r"\bhelp me fix this issue\b", "fix this issue"),
    (r"\bplease explain what is wrong and give me\b", "Provide"),
]

_FILLER_MODERATE: list[tuple[str, str]] = [
    (r"\bover and over(?: again)?\b", ""),
    (r"\bagain and again\b", ""),
    (r"\brepeatedly\b", ""),
    (r"\bi(?:'m| am) (?:still |always )?(?:getting|seeing|having)\b", "I get"),
    (r"\bfor some reason\b", ""),
    (r"\bfor whatever reason\b", ""),
    (r"\bat this point\b", ""),
    (r"\bas you can see\b", ""),
    (r"\bas mentioned (?:above|before|earlier)\b", ""),
    (r"\bi(?:'ve| have) tried everything\b", ""),
    (r"\bi(?:'ve| have) been trying\b", ""),
    (r"\bnothing (?:seems to )?works?\b", ""),
    (r"\bany help (?:would be|is) (?:greatly )?appreciated\b", ""),
    (r"\bthanks in advance\b", ""),
    (r"\bplease help\b", ""),
    (r"\bi need help(?: with this)?\b", ""),
    (r"\bi really need\b", "I need"),
    (r"\bif possible\b", ""),
    (r"\bit would be great if\b", ""),
    (r"\bI would (?:really )?(?:like|appreciate)(?: it)? if you (?:could|would)\b", ""),
    (r"\bbasically\b", ""),
    (r"\bactually\b", ""),
    (r"\bjust\b", ""),
    (r"\bsimply\b", ""),
    (r"\bkindly\b", ""),
    (r"\bplease\b", ""),
]

_FILLER_AGGRESSIVE: list[tuple[str, str]] = [
    (r"\bi think (?:that )?\b", ""),
    (r"\bit seems (?:like |that )?\b", ""),
    (r"\bso (?:basically |essentially )?\b", ""),
    (r"\bthe thing is\b", ""),
    (r"\bwhat i(?:'m| am) trying to do is\b", ""),
    (r"\bwhat i want is\b", ""),
    (r"\bi(?:'m| am) trying to\b", ""),
    (r"\bI was wondering if\b", ""),
    (r"\bdo you know\b", ""),
    (r"\bis there (?:a |any )?way to\b", ""),
    (r"\bhow do i\b", ""),
    (r"\bcan someone\b", ""),
    (r"\bdoes anyone know\b", ""),
]

# --- Stop phrases: entire sentences that add zero information ---

_STOP_PHRASES_MODERATE: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"^i(?:'m| am) not sure what(?:'s| is) (?:going on|happening|wrong)\.\s*$",
        r"^i(?:'ve| have) been stuck on this for (?:a while|hours|days)\.\s*$",
        r"^any help (?:would be|is) (?:greatly )?appreciated\.?\s*$",
        r"^thanks? (?:in advance|you)\.?\s*$",
        r"^please help(?:\s+me)?\.?\s*$",
        r"^i really need help with this\.?\s*$",
        r"^i don't know what (?:to do|else to try)\.?\s*$",
        r"^i do not know what (?:to do|else to try)\.?\s*$",
        r"^nothing (?:seems to )?work(?:s|ed)?\.?\s*$",
        r"^i(?:'ve| have) tried everything\.?\s*$",
    ]
]

_STOP_PHRASES_AGGRESSIVE: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"^here is (?:the|my) (?:error|issue|problem|output|log).*[.:]\s*$",
        r"^(?:this is|it'?s) (?:the|my) (?:error|issue|problem|output|log).*[.:]\s*$",
        r"^i(?:'m| am) getting (?:the following|this) (?:error|issue|problem).*[.:]\s*$",
        r"^(?:see|check) (?:below|above|the following).*[.:]\s*$",
        r"^let me (?:explain|show you|describe).*[.:]\s*$",
        r"^so (?:basically|essentially|here'?s the (?:thing|deal)).*[.:]\s*$",
        r"^i hope (?:this|that|you) .*[.]\s*$",
    ]
]


def _build_filler_patterns(level: OptimizationLevel) -> tuple[tuple[re.Pattern[str], str], ...]:
    patterns = list(_FILLER_CONSERVATIVE)
    if level in (OptimizationLevel.MODERATE, OptimizationLevel.AGGRESSIVE):
        patterns.extend(_FILLER_MODERATE)
    if level == OptimizationLevel.AGGRESSIVE:
        patterns.extend(_FILLER_AGGRESSIVE)
    return tuple((re.compile(p, re.IGNORECASE), r) for p, r in patterns)


def _get_stop_phrases(level: OptimizationLevel) -> list[re.Pattern[str]]:
    if level == OptimizationLevel.AGGRESSIVE:
        return _STOP_PHRASES_MODERATE + _STOP_PHRASES_AGGRESSIVE
    if level == OptimizationLevel.MODERATE:
        return _STOP_PHRASES_MODERATE
    return []


# Default (conservative) for backward compat
_FILLER_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = _build_filler_patterns(OptimizationLevel.CONSERVATIVE)


@dataclass(slots=True)
class LocalTokenOptimizer:
    """Classify and optimize shell-adjacent text without any model dependency."""

    classifier: InputClassifier | None = None
    min_savings_percent: float = 5.0
    level: OptimizationLevel = OptimizationLevel.CONSERVATIVE

    def __post_init__(self) -> None:
        if self.classifier is None:
            self.classifier = InputClassifier()

    def classify(self, text: str) -> InputClassification:
        assert self.classifier is not None
        return self.classifier.classify(text)

    def optimize(self, text: str, classification: InputClassification | None = None, *, command_name: str | None = None) -> OptimizationResult:
        classification = classification or self.classify(text)
        input_tokens = estimate_tokens(text)

        if not classification.should_optimize:
            return OptimizationResult(
                original_text=text,
                optimized_text=text,
                input_type=classification.input_type,
                risk_level=classification.risk_level,
                was_optimized=False,
                input_token_estimate=input_tokens,
                optimized_token_estimate=input_tokens,
                token_savings=0,
                token_savings_percent=0.0,
                reason=classification.reason,
                command_name=command_name,
                status="preserved",
            )

        compact = _compact_text(text, classification, self.level)
        structured = _structured_prompt(text, compact, classification, self.level)
        candidates = [compact, structured]
        best: OptimizationResult | None = None
        min_score = self._effective_min_score(classification)

        for candidate in candidates:
            candidate = candidate.strip()
            if not candidate:
                continue
            penalty = _semantic_risk_penalty(text, candidate, self.level)
            candidate_tokens = estimate_tokens(candidate)
            savings = input_tokens - candidate_tokens
            savings_percent = (savings / input_tokens * 100.0) if input_tokens else 0.0
            score = optimization_score(savings_percent, penalty, 0.0)
            result = OptimizationResult(
                original_text=text,
                optimized_text=candidate,
                input_type=classification.input_type,
                risk_level=classification.risk_level,
                was_optimized=savings > 0 and score >= min_score,
                input_token_estimate=input_tokens,
                optimized_token_estimate=candidate_tokens,
                token_savings=max(0, savings),
                token_savings_percent=max(0.0, savings_percent),
                reason="local safe prompt/log compression",
                optimization_score=score,
                command_name=command_name,
                status="ok" if score >= min_score else "preserved_low_score",
                debug={"semantic_risk_penalty": penalty},
            )
            if best is None or result.optimization_score > best.optimization_score:
                best = result

        if best is None or not best.was_optimized:
            return OptimizationResult(
                original_text=text,
                optimized_text=text,
                input_type=classification.input_type,
                risk_level=classification.risk_level,
                was_optimized=False,
                input_token_estimate=input_tokens,
                optimized_token_estimate=input_tokens,
                token_savings=0,
                token_savings_percent=0.0,
                reason=classification.reason if best is None else "candidate rejected by safety score",
                optimization_score=0.0 if best is None else best.optimization_score,
                command_name=command_name,
                status="preserved",
                debug={} if best is None else best.debug,
            )
        return best

    def _effective_min_score(self, classification: InputClassification) -> float:
        if self.level == OptimizationLevel.AGGRESSIVE:
            return 0.0
        if self.level == OptimizationLevel.MODERATE:
            return min(self.min_savings_percent, 3.0)
        return self.min_savings_percent


def _protect_code_blocks(text: str) -> tuple[str, dict[str, str]]:
    protected: dict[str, str] = {}

    def repl(match: re.Match[str]) -> str:
        key = f"__MTO_CODE_BLOCK_{len(protected)}__"
        protected[key] = match.group(0)
        return key

    return _CODE_FENCE_RE.sub(repl, text), protected


def _restore_code_blocks(text: str, protected: dict[str, str]) -> str:
    restored = text
    for key, block in protected.items():
        restored = restored.replace(key, block)
    return restored


def _remove_filler(text: str, level: OptimizationLevel = OptimizationLevel.CONSERVATIVE) -> str:
    out = text
    for pattern, replacement in _build_filler_patterns(level):
        out = pattern.sub(replacement, out)
    # Clean up artifacts from aggressive removal
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\.\s*\.", ".", out)  # collapsed empty sentences
    out = re.sub(r"^\s*[.!?,;]\s*", "", out, flags=re.MULTILINE)  # leading punctuation on lines
    out = re.sub(r"\s+([.!?,;])", r"\1", out)  # space before punctuation
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def _remove_stop_phrases(text: str, level: OptimizationLevel) -> str:
    """Remove entire sentences that add no semantic value."""
    stop_phrases = _get_stop_phrases(level)
    if not stop_phrases:
        return text
    lines = text.splitlines()
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            kept.append(line)
            continue
        if any(p.match(stripped) for p in stop_phrases):
            continue
        kept.append(line)
    return "\n".join(kept)


def _dedupe_clauses(text: str, level: OptimizationLevel) -> str:
    """Collapse semantically equivalent clauses within text.

    Uses keyword-bag overlap to detect when two sentences express the same intent.
    """
    if level == OptimizationLevel.CONSERVATIVE:
        return text

    protected, blocks = _protect_code_blocks(text)
    sentences = re.split(r"(?<=[.!?])\s+", protected.strip())
    if len(sentences) <= 1:
        return text

    threshold = 0.7 if level == OptimizationLevel.AGGRESSIVE else 0.85

    kept: list[str] = []
    kept_bags: list[set[str]] = []
    removed = 0

    for sentence in sentences:
        s = sentence.strip()
        if not s:
            continue
        if s.startswith("__MTO_CODE_BLOCK_"):
            kept.append(s)
            continue
        bag = _keyword_bag(s)
        if not bag:
            kept.append(s)
            continue
        is_dup = False
        for existing_bag in kept_bags:
            if _bag_similarity(bag, existing_bag) >= threshold:
                is_dup = True
                break
        if is_dup:
            removed += 1
        else:
            kept.append(s)
            kept_bags.append(bag)

    result = " ".join(kept)
    return _restore_code_blocks(result, blocks)


_STOPWORDS = frozenset({
    "i", "me", "my", "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "this", "that", "it", "to", "and", "or", "of", "in", "on", "for", "with",
    "do", "does", "did", "have", "has", "had", "can", "could", "would", "should",
    "will", "shall", "may", "might", "not", "no", "so", "if", "but", "from",
    "at", "by", "up", "out", "about", "into", "over", "after", "before",
})


def _keyword_bag(sentence: str) -> set[str]:
    words = re.findall(r"[a-z]+", sentence.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def _bag_similarity(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    smaller = min(len(a), len(b))
    return intersection / smaller if smaller else 0.0


def _dedupe_repeated_lines(text: str) -> str:
    output: list[str] = []
    previous = None
    repeat_count = 0
    for line in text.splitlines():
        key = re.sub(r"\s+", " ", line.strip())
        if key and key == previous:
            repeat_count += 1
            continue
        if repeat_count > 0 and output:
            output.append(f"[previous line repeated {repeat_count + 1} times]")
        output.append(line.rstrip())
        previous = key
        repeat_count = 0
    if repeat_count > 0 and output:
        output.append(f"[previous line repeated {repeat_count + 1} times]")
    return "\n".join(output)


def _dedupe_repeated_paragraphs(text: str) -> str:
    paragraphs = re.split(r"\n\s*\n", text.strip())
    seen: set[str] = set()
    result: list[str] = []
    duplicates = 0
    for para in paragraphs:
        normalized = re.sub(r"\s+", " ", para.strip())
        if not normalized:
            continue
        if normalized in seen:
            duplicates += 1
            continue
        seen.add(normalized)
        result.append(para.strip())
    if duplicates:
        result.append(f"[removed {duplicates} duplicate paragraph(s)]")
    return "\n\n".join(result)


def _dedupe_repeated_sentences(text: str) -> str:
    # Deduplicate repeated prose sentences inside a paragraph while preserving
    # order.  This handles inputs such as "please fix this" repeated many times.
    protected, blocks = _protect_code_blocks(text)
    parts = re.split(r"(?<=[.!?])\s+", protected.strip())
    if len(parts) <= 1:
        return text
    seen: set[str] = set()
    output: list[str] = []
    removed = 0
    for part in parts:
        sentence = part.strip()
        if not sentence:
            continue
        if sentence.startswith("__MTO_CODE_BLOCK_"):
            output.append(sentence)
            continue
        normalized = re.sub(r"\s+", " ", sentence.lower().strip(" .!?"))
        if normalized in seen:
            removed += 1
            continue
        seen.add(normalized)
        output.append(sentence)
    result = " ".join(output)
    if removed >= 2:
        result += f"\n[removed {removed} duplicate sentence(s)]"
    return _restore_code_blocks(result, blocks)


def _dedupe_tracebacks(text: str) -> str:
    parts = _TRACEBACK_START_RE.split(text)
    if len(parts) <= 2:
        return text

    prefix = parts[0].rstrip()
    unique_blocks: list[str] = []
    seen: set[str] = set()
    suffix_lines: list[str] = []
    removed = 0

    for part in parts[1:]:
        raw = "Traceback (most recent call last):" + part
        block_lines: list[str] = []
        trailing_lines: list[str] = []
        after_final_error = False
        for line in raw.splitlines():
            stripped = line.strip()
            if after_final_error:
                if stripped:
                    trailing_lines.append(line)
                continue
            block_lines.append(line.rstrip())
            if stripped and _FINAL_ERROR_RE.match(stripped) and not stripped.lower().startswith("traceback"):
                after_final_error = True

        block = "\n".join(block_lines).strip()
        normalized = re.sub(r"\s+", " ", block)
        if normalized in seen:
            removed += 1
        else:
            seen.add(normalized)
            unique_blocks.append(block)
        for line in trailing_lines:
            if line.strip() and line.strip() not in {x.strip() for x in suffix_lines}:
                suffix_lines.append(line.rstrip())

    output: list[str] = []
    if prefix.strip():
        output.append(prefix)
    output.extend(unique_blocks)
    if suffix_lines:
        output.append("\n".join(suffix_lines))
    if removed:
        output.append(f"[removed {removed} duplicate traceback block(s)]")
    return "\n\n".join(part for part in output if part.strip())


def _compress_large_logs(text: str, *, max_lines: int = 80) -> str:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    error_lines = [line for line in lines if re.search(r"error|exception|failed|fatal|critical|panic", line, re.IGNORECASE)]
    path_lines = [line for line in lines if _PATH_RE.search(line)]
    selected: list[str] = []
    for line in lines[:15] + error_lines[-30:] + path_lines[-20:] + lines[-15:]:
        if line not in selected:
            selected.append(line)
    return "\n".join(selected[:max_lines]) + f"\n[compressed log from {len(lines)} to {min(len(selected), max_lines)} lines]"


def _compact_text(text: str, classification: InputClassification, level: OptimizationLevel = OptimizationLevel.CONSERVATIVE) -> str:
    masked, protected = _protect_code_blocks(text)
    compact = _remove_filler(masked, level)
    compact = _remove_stop_phrases(compact, level)
    compact = _dedupe_clauses(compact, level)
    compact = _dedupe_tracebacks(compact)
    compact = _dedupe_repeated_sentences(compact)
    compact = _dedupe_repeated_paragraphs(compact)
    compact = _dedupe_repeated_lines(compact)
    if classification.input_type in {"debugging_request", "log_or_traceback", "mixed_input"}:
        compact = _compress_large_logs(compact)
    return _restore_code_blocks(compact, protected).strip()


def _first_meaningful_line(text: str) -> str:
    for line in text.splitlines():
        cleaned = line.strip()
        if cleaned:
            return cleaned
    return ""


def _extract_constraints(text: str) -> list[str]:
    constraints: list[str] = []
    for line in text.splitlines():
        lower = line.lower()
        if any(marker in lower for marker in ["must", "do not", "don't", "keep", "preserve", "without", "never"]):
            cleaned = line.strip(" -\t")
            if cleaned and cleaned not in constraints:
                constraints.append(cleaned)
    return constraints[:8]


def _derive_task(text: str, classification: InputClassification) -> str:
    if classification.input_type in {"debugging_request", "log_or_traceback"}:
        return "Diagnose the error and provide a fix."
    if classification.input_type == "code_instruction":
        return "Apply the requested code change while preserving behavior."
    if classification.input_type == "mixed_input":
        return "Complete the requested task while preserving commands/code exactly."
    first = _remove_filler(_first_meaningful_line(text)).rstrip(".")
    if not first:
        return "Complete the requested task."
    if len(first) > 140:
        first = first[:137].rstrip() + "..."
    return first[:1].upper() + first[1:] + "."


def _structured_prompt(original: str, compact: str, classification: InputClassification, level: OptimizationLevel = OptimizationLevel.CONSERVATIVE) -> str:
    task = _derive_task(original, classification)
    constraints = _extract_constraints(original)
    context = compact.strip()
    first = _first_meaningful_line(context)
    if first and first.lower().rstrip(".") in task.lower():
        context = "\n".join(context.splitlines()[1:]).strip()

    if level == OptimizationLevel.AGGRESSIVE:
        # Terse imperative output, no verbose section headers for simple prompts
        parts: list[str] = [task]
        if constraints:
            parts.append("Constraints: " + "; ".join(constraints))
        if context and context.lower().rstrip(".") != task.lower().rstrip("."):
            parts.append(context)
        return "\n".join(parts).strip()

    sections: list[tuple[str, str]] = [("Task", task)]
    if constraints:
        sections.append(("Constraints", "\n".join(f"- {item}" for item in constraints)))
    if context:
        title = "Input" if classification.input_type == "code_instruction" else "Context"
        sections.append((title, context))
    if classification.input_type in {"debugging_request", "log_or_traceback"}:
        sections.append(("Output", "1. Root cause\n2. Fix command or code change\n3. Verification step"))
    elif classification.input_type == "code_instruction":
        sections.append(("Output", "Minimal patch and verification steps."))
    elif classification.input_type == "mixed_input":
        sections.append(("Output", "Answer the request without rewriting executable commands unless explicitly asked."))
    return "\n\n".join(f"{name}:\n{body.strip()}" for name, body in sections if body.strip()).strip()


def _extract_final_error_line(text: str) -> str | None:
    matches = [m.group(0).strip() for m in _FINAL_ERROR_RE.finditer(text)]
    return matches[-1] if matches else None


def _extract_shell_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if _SHELL_LINE_RE.search(line)]


def _semantic_risk_penalty(original: str, candidate: str, level: OptimizationLevel = OptimizationLevel.CONSERVATIVE) -> float:
    penalty = 0.0

    for block in dict.fromkeys(_CODE_FENCE_RE.findall(original)):
        if block not in candidate:
            penalty += 80.0

    for path in dict.fromkeys(_PATH_RE.findall(original)):
        cleaned_path = path.strip()
        if cleaned_path and cleaned_path not in candidate:
            penalty += 12.0

    final_error = _extract_final_error_line(original)
    if final_error and final_error not in candidate:
        penalty += 70.0

    for shell_line in _extract_shell_lines(original):
        if shell_line and shell_line not in candidate:
            penalty += 25.0

    # In aggressive mode, reduce penalty for pure prose inputs (no code/paths/commands)
    if level == OptimizationLevel.AGGRESSIVE and penalty <= 0.0:
        return 0.0
    if level == OptimizationLevel.AGGRESSIVE:
        penalty *= 0.5

    return min(100.0, penalty)


def _try_model_compress(text: str) -> str | None:
    """Attempt model-based compression. Returns None if unavailable or unhelpful."""
    from . import compressor
    if not compressor.is_available():
        return None
    return compressor.compress(text)


class PromptOptimizer:
    """Compatibility optimizer used by ShellTokenOptimizer.

    Returns the tuple expected by the shell middleware:
    ``(optimized_text, was_optimized, reason, score)``.  For AI-bound text we
    prefer the compact structured prompt when it is still shorter than input.
    """

    def __init__(self, level: OptimizationLevel = OptimizationLevel.CONSERVATIVE) -> None:
        self.level = level

    def optimize(
        self,
        text: str,
        classification: InputClassification,
        *,
        historical_success_bonus: float = 0.0,
        min_score: float = 0.0,
    ) -> tuple[str, bool, str, float]:
        if not classification.should_optimize:
            return text, False, classification.reason, 0.0

        effective_min = min_score
        if self.level == OptimizationLevel.AGGRESSIVE:
            effective_min = 0.0
        elif self.level == OptimizationLevel.MODERATE:
            effective_min = min(min_score, 3.0)

        input_tokens = estimate_tokens(text)
        compact = _compact_text(text, classification, self.level)
        structured = _structured_prompt(text, compact, classification, self.level)

        candidates = [structured, compact] if classification.input_type in {
            "ai_prompt",
            "debugging_request",
            "log_or_traceback",
            "mixed_input",
            "code_instruction",
        } else [compact, structured]

        # Try local model compression on the rule-cleaned text
        if self.level in (OptimizationLevel.MODERATE, OptimizationLevel.AGGRESSIVE):
            model_result = _try_model_compress(compact)
            if model_result:
                candidates.append(model_result)

        best: tuple[str, float, int] | None = None
        for candidate in candidates:
            candidate = candidate.strip()
            if not candidate:
                continue
            candidate_tokens = estimate_tokens(candidate)
            if candidate_tokens >= input_tokens:
                continue
            savings_percent = (input_tokens - candidate_tokens) / input_tokens * 100.0 if input_tokens else 0.0
            penalty = _semantic_risk_penalty(text, candidate, self.level)
            score = optimization_score(savings_percent, penalty, historical_success_bonus)
            if score >= effective_min:
                return candidate, True, "local safe prompt/log compression", score
            if best is None or score > best[1]:
                best = (candidate, score, candidate_tokens)

        if best is not None:
            return text, False, "candidate rejected by local safety score", best[1]
        return text, False, "optimization did not reduce token estimate", 0.0

