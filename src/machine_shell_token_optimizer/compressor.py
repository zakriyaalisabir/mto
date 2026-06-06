"""Optional local model compressor using llama-cpp-python with a GGUF model.

Activates only when ``llama_cpp`` is installed.  The model is downloaded once
from HuggingFace Hub and cached locally under ``~/.local/share/mto/models/``.

Install the optional dependency:
    pip install -e ".[model]"
    mto model download
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

_MODEL_REPO = "Qwen/Qwen2-0.5B-Instruct-GGUF"
_MODEL_FILE = "qwen2-0_5b-instruct-q4_0.gguf"
_MODELS_DIR = Path.home() / ".local" / "share" / "mto" / "models"

_lock = threading.Lock()
_llm = None
_load_attempted = False

INFERENCE_TIMEOUT_MS = 2000  # generous for first call; model stays warm after


def is_available() -> bool:
    """Return True if llama-cpp-python is importable."""
    try:
        import llama_cpp  # noqa: F401
        return True
    except ImportError:
        return False


def _model_path() -> Path:
    return _MODELS_DIR / _MODEL_FILE


def is_downloaded() -> bool:
    """Return True if the GGUF model file exists locally."""
    return _model_path().exists()


def download_model() -> str:
    """Download the GGUF model from HuggingFace Hub. Returns local path."""
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        raise RuntimeError("huggingface-hub is required: pip install mto[model]")
    _MODELS_DIR.mkdir(parents=True, exist_ok=True)
    path = hf_hub_download(
        repo_id=_MODEL_REPO,
        filename=_MODEL_FILE,
        local_dir=str(_MODELS_DIR),
    )
    return path


def model_status() -> dict[str, object]:
    """Return status info about the local model."""
    return {
        "model_name": f"{_MODEL_REPO}/{_MODEL_FILE}",
        "backend": "llama-cpp-python",
        "backend_available": is_available(),
        "model_downloaded": is_downloaded(),
        "model_path": str(_model_path()),
        "loaded_in_memory": _llm is not None,
    }


def _ensure_loaded() -> bool:
    """Lazy-load the GGUF model. Returns True if ready."""
    global _llm, _load_attempted
    if _llm is not None:
        return True
    with _lock:
        if _llm is not None:
            return True
        if _load_attempted:
            return False
        _load_attempted = True
        if not is_downloaded():
            return False
        try:
            import os
            import sys
            from llama_cpp import Llama
            # Suppress llama.cpp stderr warnings
            stderr_fd = sys.stderr.fileno()
            old_stderr = os.dup(stderr_fd)
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, stderr_fd)
            try:
                _llm = Llama(
                    model_path=str(_model_path()),
                    n_ctx=512,
                    n_threads=2,
                    verbose=False,
                )
            finally:
                os.dup2(old_stderr, stderr_fd)
                os.close(old_stderr)
                os.close(devnull)
            return True
        except Exception:
            return False


def compress(text: str, *, max_tokens: int = 64) -> str | None:
    """Compress text using the local GGUF model with few-shot prompting.

    Returns the compressed text, or None if unavailable/fails/longer than input.
    """
    if not is_available() or not _ensure_loaded():
        return None
    try:
        start = time.monotonic()

        prompt = (
            "Rewrite each input in fewer words. Keep errors, paths, and commands exactly.\n\n"
            "Input: Please please can you help me fix this error. I keep getting this error over and over again. I don't know what to do.\n"
            "Output: Fix this recurring error.\n\n"
            "Input: I really need help with this issue. Can you please explain what is wrong and give me the correct command to fix it. I have been stuck on this for hours.\n"
            "Output: Explain error and provide fix command.\n\n"
            f"Input: {text}\n"
            "Output:"
        )

        result = _llm(
            prompt,
            max_tokens=max_tokens,
            temperature=0.0,
            stop=["\n", "Input:"],
        )
        elapsed_ms = (time.monotonic() - start) * 1000
        if elapsed_ms > INFERENCE_TIMEOUT_MS:
            return None

        output = result["choices"][0]["text"].strip()
        if not output or len(output) >= len(text):
            return None
        return output
    except Exception:
        return None
