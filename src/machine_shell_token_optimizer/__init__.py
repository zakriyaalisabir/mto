"""Shell-native local token optimizer for bash/zsh.

The package is independent of any LLM, model, or hosted service.  It observes
shell commands, preserves commands by default, and can locally optimize text
payloads only when explicitly invoked or wrapped.
"""

from .classifier import InputClassifier
from . import compressor
from .middleware import ShellTokenOptimizer, TokenOptimizationMiddleware
from .models import InputClassification, OptimizationLevel, OptimizationResult, ShellCommandEvent, ShellConfig
from .shell import generate_shell_hook, install_shell_hook, shell_precmd, shell_preexec, uninstall_shell_hook
from .tokenizer import estimate_tokens

__all__ = [
    "InputClassifier",
    "InputClassification",
    "OptimizationLevel",
    "OptimizationResult",
    "ShellCommandEvent",
    "ShellConfig",
    "ShellTokenOptimizer",
    "TokenOptimizationMiddleware",
    "compressor",
    "estimate_tokens",
    "generate_shell_hook",
    "install_shell_hook",
    "shell_preexec",
    "shell_precmd",
    "uninstall_shell_hook",
]
