"""Optional local model compressor using T5-small for paraphrase compression.

Activates only when ``transformers`` and ``torch`` are installed.  No network
call is made after the initial model download (which is cached by HuggingFace
under ``~/.cache/huggingface/``).

Install the optional dependency:
    pip install -e ".[model]"
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

_MODEL_NAME = "hetpandya/t5-small-tapaco"
_lock = threading.Lock()
_model = None
_tokenizer = None
_load_attempted = False

# Hard timeout to never block the shell
INFERENCE_TIMEOUT_MS = 500


def is_available() -> bool:
    """Return True if the model backend (transformers + torch) is importable."""
    try:
        import transformers  # noqa: F401
        import torch  # noqa: F401
        return True
    except ImportError:
        return False


def is_downloaded() -> bool:
    """Return True if the model files are already cached locally."""
    if not is_available():
        return False
    try:
        from transformers.utils import cached_file
        cached_file(_MODEL_NAME, "config.json", _raise_exceptions_for_missing_entries=False)
        return True
    except Exception:
        # Fallback: check HF cache directory
        cache_dir = Path.home() / ".cache" / "huggingface" / "hub"
        model_dir = cache_dir / f"models--{_MODEL_NAME.replace('/', '--')}"
        return model_dir.exists()


def download_model() -> str:
    """Download the model to local HuggingFace cache. Returns cache path."""
    if not is_available():
        raise RuntimeError("transformers and torch are required: pip install mto[model]")
    from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
    tokenizer = AutoTokenizer.from_pretrained(_MODEL_NAME)
    model = AutoModelForSeq2SeqLM.from_pretrained(_MODEL_NAME)
    cache_dir = Path.home() / ".cache" / "huggingface" / "hub"
    model_dir = cache_dir / f"models--{_MODEL_NAME.replace('/', '--')}"
    return str(model_dir)


def model_status() -> dict[str, object]:
    """Return status info about the local model."""
    return {
        "model_name": _MODEL_NAME,
        "backend_available": is_available(),
        "model_downloaded": is_downloaded() if is_available() else False,
        "loaded_in_memory": _model is not None,
    }


def _ensure_loaded() -> bool:
    """Lazy-load model and tokenizer. Returns True if ready."""
    global _model, _tokenizer, _load_attempted
    if _model is not None:
        return True
    with _lock:
        if _model is not None:
            return True
        if _load_attempted:
            return False
        _load_attempted = True
        try:
            from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
            import torch  # noqa: F401
            _tokenizer = AutoTokenizer.from_pretrained(_MODEL_NAME)
            _model = AutoModelForSeq2SeqLM.from_pretrained(_MODEL_NAME)
            _model.eval()
            return True
        except Exception:
            return False


def compress(text: str, *, max_length: int = 64) -> str | None:
    """Compress text using the local T5 paraphrase model.

    Returns the compressed text, or None if the model is unavailable, fails,
    or produces output longer than the input.
    """
    if not is_available() or not _ensure_loaded():
        return None
    try:
        import torch
        start = time.monotonic()
        input_ids = _tokenizer(
            f"paraphrase: {text}",
            return_tensors="pt",
            max_length=512,
            truncation=True,
        ).input_ids

        with torch.no_grad():
            outputs = _model.generate(
                input_ids,
                max_length=max_length,
                num_beams=4,
                early_stopping=True,
            )

        elapsed_ms = (time.monotonic() - start) * 1000
        if elapsed_ms > INFERENCE_TIMEOUT_MS:
            return None  # too slow, discard

        result = _tokenizer.decode(outputs[0], skip_special_tokens=True)
        if not result or len(result) >= len(text):
            return None
        return result
    except Exception:
        return None
