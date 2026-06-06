"""bash/zsh integration helpers.

The shell hook observes every interactive command.  It does not rewrite commands.
Configured wrappers can opt selected CLI tools into local prompt optimization.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from .classifier import InputClassifier
from .config import load_config
from .middleware import ShellTokenOptimizer
from .models import OptimizationLevel, ShellConfig
from .redaction import redact_secrets
from .storage import ShellTokenStorage

BEGIN_MARKER = "# >>> mto shell integration >>>"
END_MARKER = "# <<< mto shell integration <<<"


def rcfile_for_shell(shell: str) -> Path:
    shell = shell.lower()
    if shell == "bash":
        return Path.home() / ".bashrc"
    if shell == "zsh":
        return Path.home() / ".zshrc"
    if shell == "sh":
        return Path.home() / ".profile"
    raise ValueError("shell must be 'bash', 'zsh', or 'sh'")


def generate_shell_hook(shell: str, *, wrap_commands: Sequence[str] | None = None) -> str:
    shell = shell.lower()
    wraps = " ".join(shlex.quote(cmd) for cmd in (wrap_commands or []))
    if shell == "bash":
        return _bash_hook(wraps)
    if shell == "zsh":
        return _zsh_hook(wraps)
    if shell == "sh":
        return _sh_hook(wraps)
    raise ValueError("shell must be 'bash', 'zsh', or 'sh'")


def install_shell_hook(shell: str, rcfile: str | Path | None = None, *, wrap_commands: Sequence[str] | None = None) -> Path:
    path = Path(rcfile).expanduser() if rcfile else rcfile_for_shell(shell)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    without_old = remove_managed_block(existing)
    wrap_arg = ""
    if wrap_commands:
        wrap_arg = " --wrap " + shlex.quote(",".join(wrap_commands))
    block = f"{BEGIN_MARKER}\neval \"$(mto shell-hook {shell}{wrap_arg})\"\n{END_MARKER}\n"
    new_text = without_old.rstrip() + "\n\n" + block
    path.write_text(new_text, encoding="utf-8")
    return path


def uninstall_shell_hook(shell: str, rcfile: str | Path | None = None) -> Path:
    path = Path(rcfile).expanduser() if rcfile else rcfile_for_shell(shell)
    if not path.exists():
        return path
    existing = path.read_text(encoding="utf-8")
    path.write_text(remove_managed_block(existing).rstrip() + "\n", encoding="utf-8")
    return path


def remove_managed_block(text: str) -> str:
    pattern = re.compile(rf"\n?{re.escape(BEGIN_MARKER)}[\s\S]*?{re.escape(END_MARKER)}\n?", re.MULTILINE)
    return pattern.sub("\n", text)


def shell_preexec(command: str, *, shell: str, pid: int | None = None, cwd: str | None = None, db_path: str | None = None) -> str | None:
    cfg = load_config()
    if not cfg.enabled or not cfg.observe_all_commands:
        return None
    command = command.strip()
    if not command or _should_ignore_command(command):
        return None
    storage = ShellTokenStorage(db_path or cfg.db_path)
    classifier = InputClassifier()
    classification = classifier.classify(command)
    try:
        # Opportunistic history cleanup (cheap check)
        storage.cleanup_history(cfg.history_days)
        return storage.log_shell_event(
            raw_command=command,
            shell=shell,
            pid=pid or os.getpid(),
            cwd=cwd or os.getcwd(),
            input_type=classification.input_type,
            risk_level=classification.risk_level,
            was_modified=False,
            optimized_preview="",
        )
    finally:
        storage.close()


def shell_precmd(*, shell: str, pid: int | None = None, status: int = 0, db_path: str | None = None) -> str | None:
    cfg = load_config()
    if not cfg.enabled or not cfg.observe_all_commands:
        return None
    storage = ShellTokenStorage(db_path or cfg.db_path)
    try:
        return storage.complete_latest_shell_event(shell=shell, pid=pid or os.getpid(), exit_code=status)
    finally:
        storage.close()


def execute_with_optional_optimization(
    argv: Sequence[str],
    *,
    force_optimize: bool = False,
    dry_run: bool = False,
    db_path: str | None = None,
    timeout: float | None = None,
    level: OptimizationLevel = OptimizationLevel.CONSERVATIVE,
) -> int:
    """Run a command, optionally optimizing AI-bound argument/stdin payloads.

    This function is model-independent.  It optimizes local text only, then runs
    the requested executable with ``subprocess.run(shell=False)``.
    """

    if not argv:
        raise ValueError("no command provided")

    cfg = load_config()
    command_name = Path(argv[0]).name
    full_command = " ".join(argv)

    # Check exclude_commands
    if _is_excluded(full_command, cfg.exclude_commands):
        completed = subprocess.run(argv, text=True, check=False,
                                   timeout=timeout or cfg.default_timeout_seconds)
        return int(completed.returncode)

    storage = ShellTokenStorage(db_path or cfg.db_path)
    optimizer = ShellTokenOptimizer(db_path=db_path or cfg.db_path, storage=storage, enabled=cfg.enabled, level=level)
    new_argv = list(argv)

    stdin_text = _read_stdin_if_available()

    should_try_optimize = force_optimize or command_name in cfg.optimize_commands
    optimization_payload = ""
    payload_location: tuple[str, int | None] | None = None

    if stdin_text:
        optimization_payload = stdin_text
        payload_location = ("stdin", None)
    elif should_try_optimize:
        extracted = _extract_argv_payload(new_argv)
        if extracted is not None:
            index, payload = extracted
            optimization_payload = payload
            payload_location = ("argv", index)

    result = None
    if should_try_optimize and optimization_payload:
        result = optimizer.process(optimization_payload, command_name=command_name)
        if payload_location and result.was_optimized:
            location, index = payload_location
            if location == "stdin":
                stdin_text = result.optimized_text
            elif location == "argv" and index is not None:
                new_argv[index] = result.optimized_text

    if dry_run:
        import json

        print(
            json.dumps(
                {
                    "command": argv[0],
                    "original_argv": list(argv),
                    "effective_argv": new_argv,
                    "stdin_was_present": stdin_text is not None,
                    "optimized": result.was_optimized if result else False,
                    "optimization": None
                    if result is None
                    else {
                        "input_type": result.input_type,
                        "risk_level": result.risk_level,
                        "input_tokens": result.input_token_estimate,
                        "optimized_tokens": result.optimized_token_estimate,
                        "token_savings": result.token_savings,
                        "token_savings_percent": result.token_savings_percent,
                        "reason": result.reason,
                        "optimized_text": result.optimized_text,
                    },
                },
                indent=2,
            )
        )
        return 0

    try:
        completed = subprocess.run(
            new_argv,
            input=stdin_text,
            text=True,
            timeout=timeout if timeout is not None else cfg.default_timeout_seconds,
            check=False,
            capture_output=cfg.tee_enabled and cfg.tee_mode != "never",
        )
        # Tee system: save output on failure
        if cfg.tee_enabled and cfg.tee_mode != "never" and completed.stdout:
            output = (completed.stdout or "") + (completed.stderr or "")
            if output:
                from .tee import tee_output
                tee_path = tee_output(
                    command_name, output, completed.returncode,
                    tee_dir=cfg.tee_dir, mode=cfg.tee_mode, max_files=cfg.tee_max_files,
                )
                if tee_path:
                    print(f"[full output: {tee_path}]", file=sys.stderr)
            # Print stdout/stderr since we captured it
            if completed.stdout:
                sys.stdout.write(completed.stdout)
            if completed.stderr:
                sys.stderr.write(completed.stderr)
        return int(completed.returncode)
    finally:
        optimizer.close()


def _read_stdin_if_available() -> str | None:
    """Read stdin only when a pipe/file has data ready.

    subprocess-based tests and some shell hooks can have a non-TTY stdin that
    is not actually carrying payload data. A blind sys.stdin.read() can block
    forever in those environments, so this helper reads only from regular files
    or from pipes/sockets that are immediately readable.
    """

    if sys.stdin.isatty():
        return None
    try:
        import select
        import stat

        fd = sys.stdin.fileno()
        mode = os.fstat(fd).st_mode
        if stat.S_ISREG(mode):
            data = sys.stdin.read()
            return data if data else None
        if stat.S_ISFIFO(mode) or stat.S_ISSOCK(mode):
            ready, _, _ = select.select([sys.stdin], [], [], 0)
            if not ready:
                return None
            data = sys.stdin.read()
            return data if data else None
    except (OSError, ValueError):
        return None
    return None


def _extract_argv_payload(argv: list[str]) -> tuple[int, str] | None:
    if len(argv) < 2:
        return None
    prompt_flags = {"--prompt", "-p", "--message", "-m", "--input", "--text"}
    for idx, arg in enumerate(argv[:-1]):
        if arg in prompt_flags and idx + 1 < len(argv):
            return idx + 1, argv[idx + 1]
        for flag in prompt_flags:
            if arg.startswith(flag + "="):
                return idx, arg.split("=", 1)[1]
    # Fallback: optimize the longest natural-language-like argument.
    candidates = [(idx, arg) for idx, arg in enumerate(argv[1:], start=1) if len(arg.split()) >= 5 or len(arg) > 80]
    if not candidates:
        return None
    return max(candidates, key=lambda item: len(item[1]))


def _should_ignore_command(command: str) -> bool:
    stripped = command.strip()
    ignore_prefixes = (
        "mto ",
        "command mto ",
        "__mto_",
        "trap ",
        "PROMPT_COMMAND=",
        "precmd_functions",
        "preexec_functions",
        "eval \"$(mto shell-hook",
        "history -a",
    )
    return stripped.startswith(ignore_prefixes)


def _is_excluded(command: str, exclude_patterns: list[str]) -> bool:
    """Check if command matches any exclude pattern."""
    if not exclude_patterns:
        return False
    # Strip env prefixes (VAR=val, sudo)
    stripped = re.sub(r"^(?:sudo\s+|[A-Za-z_][A-Za-z0-9_]*=[^\s]*\s+)*", "", command.strip())
    for pattern in exclude_patterns:
        if pattern.startswith("^"):
            try:
                if re.search(pattern, stripped):
                    return True
            except re.error:
                if stripped.startswith(pattern.lstrip("^")):
                    return True
        elif stripped == pattern or stripped.startswith(pattern + " "):
            return True
    return False


def _bash_hook(wraps: str) -> str:
    template = r'''# mto shell integration: bash
# Observes commands with DEBUG trap. Proxies output compression in agent sessions.
export MTO_SHELL_INTEGRATION=1
export MTO_WRAP_COMMANDS="${MTO_WRAP_COMMANDS:-__MTO_WRAP_DEFAULT__}"

__mto_preexec() {
  local __mto_status=$?
  [[ "${MTO_HOOK_GUARD:-0}" == "1" ]] && return $__mto_status
  [[ "${MTO_ENABLED:-1}" == "0" ]] && return $__mto_status
  local __mto_cmd="$BASH_COMMAND"
  case "$__mto_cmd" in
    __mto_*|mto_*|mto\ *|command\ mto\ *|trap\ *|PROMPT_COMMAND=*) return $__mto_status ;;
  esac
  export MTO_HOOK_GUARD=1
  command mto shell-preexec --shell bash --pid "$$" -- "$__mto_cmd" >/dev/null 2>&1 || true
  export MTO_HOOK_GUARD=0
  export MTO_LAST_OBSERVED_COMMAND="$__mto_cmd"
  return $__mto_status
}

__mto_precmd() {
  local __mto_status=$?
  [[ "${MTO_HOOK_GUARD:-0}" == "1" ]] && return $__mto_status
  [[ -z "${MTO_LAST_OBSERVED_COMMAND:-}" ]] && return $__mto_status
  export MTO_HOOK_GUARD=1
  command mto shell-precmd --shell bash --pid "$$" --status "$__mto_status" >/dev/null 2>&1 || true
  unset MTO_LAST_OBSERVED_COMMAND
  export MTO_HOOK_GUARD=0
  return $__mto_status
}

mto_unmount() {
  trap - DEBUG
  PROMPT_COMMAND="${PROMPT_COMMAND#__mto_precmd;}"
  [ "$PROMPT_COMMAND" = "__mto_precmd" ] && PROMPT_COMMAND=""
  export MTO_ENABLED=0
  unset MTO_SHELL_INTEGRATION MTO_WRAP_COMMANDS MTO_LAST_OBSERVED_COMMAND MTO_HOOK_GUARD MTO_AGENT_SESSION
  # Keep hook functions defined to avoid DEBUG-trap race conditions in bash.
}

# Proxy wrapper for explicit use: mto proxy -- <cmd>
__mto_exec_wrapper() {
  local __mto_cmd="$1"
  shift
  command mto exec -- "$__mto_cmd" "$@"
}

__mto_proxy_wrapper() {
  local __mto_cmd="$1"
  shift
  command mto proxy -- "$__mto_cmd" "$@"
}

# Activate agent session: proxy dev commands that are NOT already aliased
mto_agent() {
  export MTO_AGENT_SESSION=1
  for __mto_cmd in git docker kubectl cargo npm pnpm yarn pytest go ruff eslint find cat; do
    # Skip if user has an alias for this command
    alias "$__mto_cmd" >/dev/null 2>&1 && continue
    if command -v "$__mto_cmd" >/dev/null 2>&1; then
      eval "$__mto_cmd() { __mto_proxy_wrapper $__mto_cmd \"\$@\"; }"
    fi
  done
  unset __mto_cmd
  echo "mto: agent session active — command outputs will be compressed"
}

for __mto_cmd in $MTO_WRAP_COMMANDS; do
  if command -v "$__mto_cmd" >/dev/null 2>&1; then
    eval "$__mto_cmd() { __mto_exec_wrapper $__mto_cmd \"\$@\"; }"
  fi
done
unset __mto_cmd

# Auto-activate if MTO_AGENT_SESSION was already set
if [[ "${MTO_AGENT_SESSION:-0}" == "1" ]]; then
  mto_agent >/dev/null 2>&1
fi

# Enable observation only after the hook has fully installed, so setup
# commands are not recorded and non-interactive test shells do not recurse.
case ";${PROMPT_COMMAND:-};" in
  *";__mto_precmd;"*) ;;
  *) PROMPT_COMMAND="__mto_precmd${PROMPT_COMMAND:+;$PROMPT_COMMAND}" ;;
esac
trap '__mto_preexec' DEBUG
'''
    return template.replace("__MTO_WRAP_DEFAULT__", wraps)


def _zsh_hook(wraps: str) -> str:
    template = r'''# mto shell integration: zsh
# Observes commands with preexec/precmd. Does not rewrite shell commands.
export MTO_SHELL_INTEGRATION=1
export MTO_WRAP_COMMANDS="${MTO_WRAP_COMMANDS:-__MTO_WRAP_DEFAULT__}"

autoload -Uz add-zsh-hook 2>/dev/null || true

__mto_zsh_preexec() {
  local __mto_cmd="$1"
  [[ "${MTO_HOOK_GUARD:-0}" == "1" ]] && return
  [[ "${MTO_ENABLED:-1}" == "0" ]] && return
  case "$__mto_cmd" in
    __mto_*|mto_*|mto\ *|command\ mto\ *) return ;;
  esac
  export MTO_HOOK_GUARD=1
  command mto shell-preexec --shell zsh --pid "$$" -- "$__mto_cmd" >/dev/null 2>&1 || true
  export MTO_LAST_OBSERVED_COMMAND="$__mto_cmd"
  export MTO_HOOK_GUARD=0
}

__mto_zsh_precmd() {
  local __mto_status=$?
  [[ "${MTO_HOOK_GUARD:-0}" == "1" ]] && return
  [[ -z "${MTO_LAST_OBSERVED_COMMAND:-}" ]] && return
  export MTO_HOOK_GUARD=1
  command mto shell-precmd --shell zsh --pid "$$" --status "$__mto_status" >/dev/null 2>&1 || true
  unset MTO_LAST_OBSERVED_COMMAND
  export MTO_HOOK_GUARD=0
}

if typeset -f add-zsh-hook >/dev/null 2>&1; then
  add-zsh-hook preexec __mto_zsh_preexec
  add-zsh-hook precmd __mto_zsh_precmd
else
  preexec_functions+=(__mto_zsh_preexec)
  precmd_functions+=(__mto_zsh_precmd)
fi

mto_unmount() {
  preexec_functions=(${preexec_functions:#__mto_zsh_preexec})
  precmd_functions=(${precmd_functions:#__mto_zsh_precmd})
  unset MTO_SHELL_INTEGRATION MTO_WRAP_COMMANDS MTO_LAST_OBSERVED_COMMAND MTO_HOOK_GUARD MTO_AGENT_SESSION
  unfunction __mto_zsh_preexec __mto_zsh_precmd __mto_exec_wrapper __mto_proxy_wrapper mto_unmount mto_agent 2>/dev/null || true
}

__mto_exec_wrapper() {
  local __mto_cmd="$1"
  shift
  command mto exec -- "$__mto_cmd" "$@"
}

__mto_proxy_wrapper() {
  local __mto_cmd="$1"
  shift
  command mto proxy -- "$__mto_cmd" "$@"
}

# Activate agent session: proxy dev commands that are NOT already aliased
mto_agent() {
  export MTO_AGENT_SESSION=1
  for __mto_cmd in git docker kubectl cargo npm pnpm yarn pytest go ruff eslint find cat; do
    # Skip if user has an alias for this command
    alias "$__mto_cmd" >/dev/null 2>&1 && continue
    if command -v "$__mto_cmd" >/dev/null 2>&1; then
      eval "$__mto_cmd() { __mto_proxy_wrapper $__mto_cmd \"\$@\"; }"
    fi
  done
  unset __mto_cmd
  echo "mto: agent session active — command outputs will be compressed"
}

for __mto_cmd in $MTO_WRAP_COMMANDS; do
  if command -v "$__mto_cmd" >/dev/null 2>&1; then
    eval "$__mto_cmd() { __mto_exec_wrapper $__mto_cmd \"\$@\"; }"
  fi
done
unset __mto_cmd

# Auto-activate if MTO_AGENT_SESSION was already set
if [[ "${MTO_AGENT_SESSION:-0}" == "1" ]]; then
  mto_agent >/dev/null 2>&1
fi
'''
    return template.replace("__MTO_WRAP_DEFAULT__", wraps)


def _sh_hook(wraps: str) -> str:
    template = r'''# mto shell integration: POSIX sh
# POSIX sh has no portable preexec hook. Use explicit wrappers.
export MTO_SHELL_INTEGRATION=1
export MTO_WRAP_COMMANDS="${MTO_WRAP_COMMANDS:-__MTO_WRAP_DEFAULT__}"

mto_observe() {
  command mto shell-preexec --shell sh --pid "$$" -- "$*" >/dev/null 2>&1 || true
}

mto_exec() {
  command mto exec -- "$@"
}

mto_optimize() {
  command mto optimize "$*"
}

mto_classify() {
  command mto classify "$*"
}

mto_unmount() {
  unset MTO_SHELL_INTEGRATION MTO_WRAP_COMMANDS
  unset -f mto_observe mto_exec mto_optimize mto_classify mto_unmount 2>/dev/null || true
}
'''
    return template.replace("__MTO_WRAP_DEFAULT__", wraps)
