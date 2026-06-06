"""Command line interface for mto."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
import os
import sys
from pathlib import Path

from .config import load_config, write_default_config
from .middleware import ShellTokenOptimizer
from .models import OptimizationLevel
from .shell import (
    execute_with_optional_optimization,
    generate_shell_hook,
    install_shell_hook,
    shell_precmd,
    shell_preexec,
    uninstall_shell_hook,
)
from .storage import ShellTokenStorage


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except BrokenPipeError:
        return 1
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # pragma: no cover - CLI safety net
        print(f"mto: error: {exc}", file=sys.stderr)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mto",
        description="Shell-native local token optimizer and command observer for bash/zsh.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Initialize config and SQLite database")
    p_init.add_argument("--config", help="Config path; default ~/.config/mto/config.json")
    p_init.add_argument("--db-path", help="SQLite path override")
    p_init.add_argument("--force", action="store_true", help="Overwrite existing config")
    p_init.add_argument("--agent", nargs="?", const="all", help="Install agent instructions (codex, kiro-cli, or 'all')")
    p_init.set_defaults(func=cmd_init)

    p_hook = sub.add_parser("shell-hook", help="Print bash/zsh hook script for eval/source")
    p_hook.add_argument("shell", choices=["bash", "zsh", "sh"])
    p_hook.add_argument("--wrap", default="", help="Comma/space separated commands to wrap through mto exec")
    p_hook.set_defaults(func=cmd_shell_hook)

    p_install = sub.add_parser("install-shell", help="Mount/install shell integration into .bashrc/.zshrc")
    p_install.add_argument("--shell", choices=["bash", "zsh", "sh"], required=True)
    p_install.add_argument("--rcfile", help="Override rc file path")
    p_install.add_argument("--wrap", default="", help="Comma/space separated commands to wrap")
    p_install.set_defaults(func=cmd_install_shell)

    p_uninstall = sub.add_parser("uninstall-shell", help="Unmount/remove shell integration from .bashrc/.zshrc")
    p_uninstall.add_argument("--shell", choices=["bash", "zsh", "sh"], required=True)
    p_uninstall.add_argument("--rcfile", help="Override rc file path")
    p_uninstall.set_defaults(func=cmd_uninstall_shell)

    p_preexec = sub.add_parser("shell-preexec", help=argparse.SUPPRESS)
    p_preexec.add_argument("--shell", choices=["bash", "zsh", "sh"], required=True)
    p_preexec.add_argument("--pid", type=int, default=os.getpid())
    p_preexec.add_argument("--db-path")
    p_preexec.add_argument("raw", nargs=argparse.REMAINDER)
    p_preexec.set_defaults(func=cmd_shell_preexec)

    p_precmd = sub.add_parser("shell-precmd", help=argparse.SUPPRESS)
    p_precmd.add_argument("--shell", choices=["bash", "zsh", "sh"], required=True)
    p_precmd.add_argument("--pid", type=int, default=os.getpid())
    p_precmd.add_argument("--status", type=int, default=0)
    p_precmd.add_argument("--db-path")
    p_precmd.set_defaults(func=cmd_shell_precmd)

    p_opt = sub.add_parser("optimize", help="Optimize AI-bound text locally and print the result")
    p_opt.add_argument("text", nargs="*")
    p_opt.add_argument("--db-path")
    p_opt.add_argument("--json", action="store_true", help="Print detailed JSON result")
    p_opt.add_argument("--level", choices=["conservative", "moderate", "aggressive"], default=None, help="Optimization aggressiveness")
    p_opt.set_defaults(func=cmd_optimize)

    p_classify = sub.add_parser("classify", help="Classify text/command without optimizing")
    p_classify.add_argument("text", nargs="*")
    p_classify.add_argument("--db-path")
    p_classify.add_argument("--json", action="store_true")
    p_classify.set_defaults(func=cmd_classify)

    p_exec = sub.add_parser("exec", help="Run a command, optionally optimizing AI-bound stdin/args first")
    p_exec.add_argument("--optimize", action="store_true", help="Force local optimization of detected text payload")
    p_exec.add_argument("--dry-run", action="store_true", help="Print effective argv/stdin metadata; do not execute")
    p_exec.add_argument("--db-path")
    p_exec.add_argument("--timeout", type=float)
    p_exec.add_argument("--level", choices=["conservative", "moderate", "aggressive"], default=None, help="Optimization aggressiveness")
    p_exec.add_argument("argv", nargs=argparse.REMAINDER)
    p_exec.set_defaults(func=cmd_exec)

    p_stats = sub.add_parser("stats", help="Show SQLite command/optimization stats")
    p_stats.add_argument("--db-path")
    p_stats.add_argument("--json", action="store_true")
    p_stats.add_argument("--reset", action="store_true", help="Reset all stats (clear all tables)")
    p_stats.set_defaults(func=cmd_stats)

    p_audit = sub.add_parser("audit", help="Review observed commands by risk level")
    p_audit.add_argument("--risk", choices=["high", "medium", "low"], default="high", help="Filter by risk level")
    p_audit.add_argument("--limit", type=int, default=20, help="Max entries to show")
    p_audit.add_argument("--db-path")
    p_audit.add_argument("--json", action="store_true")
    p_audit.set_defaults(func=cmd_audit)

    p_feedback = sub.add_parser("feedback", help="Add feedback for an optimization run")
    p_feedback.add_argument("--id", required=True, dest="run_id")
    p_feedback.add_argument("--rating", choices=["good", "bad"], required=True)
    p_feedback.add_argument("--notes", default="")
    p_feedback.add_argument("--db-path")
    p_feedback.set_defaults(func=cmd_feedback)

    p_status = sub.add_parser("status", help="Print resolved config and database path")
    p_status.add_argument("--json", action="store_true")
    p_status.set_defaults(func=cmd_status)

    p_config = sub.add_parser("config", help="Show or create config file")
    p_config.add_argument("--create", action="store_true", help="Create config file with defaults")
    p_config.add_argument("--path", help="Custom config path")
    p_config.set_defaults(func=cmd_config)

    p_model = sub.add_parser("model", help="Manage the optional local compression model")
    model_sub = p_model.add_subparsers(dest="model_command", required=True)
    model_sub.add_parser("status", help="Show model availability and download status").set_defaults(func=cmd_model_status)
    model_sub.add_parser("download", help="Download the model to local cache").set_defaults(func=cmd_model_download)

    p_proxy = sub.add_parser("proxy", help="Run a command and compress its output before returning")
    p_proxy.add_argument("--raw", action="store_true", help="Disable output compression (passthrough + tracking)")
    p_proxy.add_argument("argv", nargs=argparse.REMAINDER)
    p_proxy.set_defaults(func=cmd_proxy)

    p_shims = sub.add_parser("install-shims", help="Install PATH shims for transparent output compression (agent sessions only)")
    p_shims.add_argument("--commands", help="Comma-separated commands to shim (default: common dev tools)")
    p_shims.add_argument("--dir", help="Shim directory (default: ~/.local/share/mto/shims)")
    p_shims.set_defaults(func=cmd_install_shims)

    p_unshims = sub.add_parser("uninstall-shims", help="Remove PATH shims")
    p_unshims.add_argument("--dir", help="Shim directory (default: ~/.local/share/mto/shims)")
    p_unshims.set_defaults(func=cmd_uninstall_shims)

    p_shims_env = sub.add_parser("shims-env", help="Print env activation for current session (eval \"$(mto shims-env)\")")
    p_shims_env.add_argument("--dir", help="Shim directory override")
    p_shims_env.set_defaults(func=cmd_shims_env)

    return parser


def cmd_init(args: argparse.Namespace) -> int:
    config_path = write_default_config(args.config, force=args.force)
    cfg = load_config(config_path)
    db_path = args.db_path or cfg.db_path
    storage = ShellTokenStorage(db_path)
    storage.close()
    print(f"config: {config_path}")
    print(f"database: {Path(db_path).expanduser() if db_path else 'default'}")
    if args.agent:
        _install_agent_instructions(args.agent)
    return 0


_MTO_AGENT_INSTRUCTIONS = """
# MTO — Machine Token Optimizer

When running shell commands, use `mto proxy --` prefix to get compressed output.
This saves context window tokens by filtering verbose command outputs.

## Usage

Instead of:
```bash
git log -20
git diff
cargo test
docker ps
kubectl get pods
cat file.py
find . -name "*.ts"
ps aux
```

Use:
```bash
mto proxy -- git log -20
mto proxy -- git diff
mto proxy -- cargo test
mto proxy -- docker ps
mto proxy -- kubectl get pods
mto proxy -- cat file.py
mto proxy -- find . -name "*.ts"
mto proxy -- ps aux
```

## Why

- `git log -50` → 433 lines becomes 50 lines (-88%)
- `cargo test` → 200 lines becomes ~5 lines (failures + summary)
- `find . -name "*.py"` → 3000+ lines becomes 31 lines (-99%)
- `ps aux` → 650 lines becomes 61 lines (-91%)

## Rules

- Always prefix shell commands with `mto proxy --` when reading output
- Do NOT prefix commands that write/modify (git push, rm, mv, docker run)
- If mto is not available, fall back to running commands directly

## Auto-Compression (Alternative)

If shims are installed, activate transparent compression with:
```bash
eval "$(mto shims-env)"
```
After this, commands like `git log`, `find`, `docker ps` are automatically compressed
without needing the `mto proxy --` prefix. Write commands pass through unchanged.
"""

_MTO_MARKER = "# MTO — Machine Token Optimizer"


def _install_agent_instructions(agent: str) -> None:
    """Install MTO instructions into agent config locations."""
    locations: list[Path] = []

    # Local AGENTS.md (current project)
    local_agents = Path.cwd() / "AGENTS.md"
    locations.append(local_agents)

    # Global ~/AGENTS.md
    locations.append(Path.home() / "AGENTS.md")

    if agent in ("all", "codex"):
        # Codex: ~/.codex/AGENTS.md
        codex_dir = Path.home() / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        locations.append(codex_dir / "AGENTS.md")

    if agent in ("all", "kiro-cli", "kiro"):
        # Kiro: ~/.kiro/AGENTS.md
        kiro_dir = Path.home() / ".kiro"
        kiro_dir.mkdir(parents=True, exist_ok=True)
        locations.append(kiro_dir / "AGENTS.md")

    for path in locations:
        _inject_instructions(path)
        print(f"agent instructions: {path}")


def _inject_instructions(path: Path) -> None:
    """Append MTO instructions to file if not already present."""
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if _MTO_MARKER in existing:
        return  # already installed
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n" + _MTO_AGENT_INSTRUCTIONS.strip() + "\n")


def cmd_shell_hook(args: argparse.Namespace) -> int:
    print(generate_shell_hook(args.shell, wrap_commands=_split_wrap(args.wrap)), end="")
    return 0


def cmd_install_shell(args: argparse.Namespace) -> int:
    path = install_shell_hook(args.shell, args.rcfile, wrap_commands=_split_wrap(args.wrap))
    print(f"installed {args.shell} integration: {path}")
    return 0


def cmd_uninstall_shell(args: argparse.Namespace) -> int:
    path = uninstall_shell_hook(args.shell, args.rcfile)
    print(f"uninstalled {args.shell} integration: {path}")
    return 0


def cmd_shell_preexec(args: argparse.Namespace) -> int:
    command = _remainder_to_text(args.raw)
    event_id = shell_preexec(command, shell=args.shell, pid=args.pid, db_path=args.db_path)
    if event_id:
        print(event_id)
    return 0


def cmd_shell_precmd(args: argparse.Namespace) -> int:
    event_id = shell_precmd(shell=args.shell, pid=args.pid, status=args.status, db_path=args.db_path)
    if event_id:
        print(event_id)
    return 0


def cmd_optimize(args: argparse.Namespace) -> int:
    from .config import is_disabled
    text = _args_or_stdin(args.text)
    if is_disabled():
        print(text)
        return 0
    level = _resolve_level(args.level)
    opt = ShellTokenOptimizer(db_path=args.db_path, level=level)
    try:
        result = opt.process(text)
        if args.json:
            print(json.dumps(asdict(result), indent=2, default=str))
        else:
            print(result.optimized_text)
    finally:
        opt.close()
    return 0


def cmd_classify(args: argparse.Namespace) -> int:
    text = _args_or_stdin(args.text)
    opt = ShellTokenOptimizer(db_path=args.db_path)
    try:
        c = opt.classify_input(text)
        if args.json:
            print(json.dumps(asdict(c), indent=2, default=str))
        else:
            print(f"{c.input_type}\t{c.risk_level}\tshould_optimize={str(c.should_optimize).lower()}\t{c.reason}")
    finally:
        opt.close()
    return 0


def cmd_exec(args: argparse.Namespace) -> int:
    argv = _strip_remainder_separator(args.argv)
    level = _resolve_level(args.level)
    return execute_with_optional_optimization(
        argv,
        force_optimize=args.optimize,
        dry_run=args.dry_run,
        db_path=args.db_path,
        timeout=args.timeout,
        level=level,
    )


def cmd_stats(args: argparse.Namespace) -> int:
    storage = ShellTokenStorage(args.db_path)
    try:
        if args.reset:
            storage.reset()
            print("stats reset")
            return 0
        stats = storage.stats()
    finally:
        storage.close()
    if args.json:
        print(json.dumps(stats, indent=2, default=str))
    else:
        print(f"shell events: {stats['shell_events']}")
        print(f"observed token estimate: {stats['observed_token_estimate']}")
        print(f"high risk events: {stats['high_risk_events']}")
        print(f"optimization runs: {stats['optimization_runs']}")
        print(f"optimized runs: {stats['optimized_runs']}")
        print(f"total token savings: {stats['total_token_savings']}")
        print(f"avg savings percent: {stats['avg_savings_percent']:.2f}")
        if stats.get("top_commands"):
            print("top commands:")
            for item in stats["top_commands"]:  # type: ignore[index]
                print(f"  {item['command_name']}: {item['usage_count']}x")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    storage = ShellTokenStorage(args.db_path)
    try:
        rows = storage.connection.execute(
            """SELECT created_at, raw_command_preview, cwd, risk_level, exit_code
               FROM shell_command_events
               WHERE risk_level = ?
               ORDER BY created_at DESC LIMIT ?""",
            (args.risk, args.limit),
        ).fetchall()
    finally:
        storage.close()
    if args.json:
        print(json.dumps([dict(r) for r in rows], indent=2, default=str))
    else:
        if not rows:
            print(f"no {args.risk}-risk commands found")
            return 0
        for r in rows:
            exit_str = f" exit={r['exit_code']}" if r['exit_code'] is not None else ""
            print(f"[{r['created_at']}] {r['raw_command_preview']}{exit_str}")
            print(f"  cwd: {r['cwd']}")
    return 0


def cmd_feedback(args: argparse.Namespace) -> int:
    storage = ShellTokenStorage(args.db_path)
    try:
        feedback_id = storage.record_feedback(args.run_id, args.rating, args.notes)
    finally:
        storage.close()
    print(feedback_id)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    cfg = load_config()
    data = {
        "enabled": cfg.enabled,
        "observe_all_commands": cfg.observe_all_commands,
        "db_path": cfg.db_path,
        "wrap_commands": cfg.wrap_commands,
        "optimize_commands": cfg.optimize_commands,
    }
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        for key, value in data.items():
            print(f"{key}: {value}")
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    from .config import default_config_path, write_default_config
    if args.create:
        path = write_default_config(args.path, force=True)
        print(f"config created: {path}")
        return 0
    config_path = Path(args.path).expanduser() if args.path else default_config_path()
    if not config_path.exists():
        print(f"no config file at {config_path}")
        print("run: mto config --create")
        return 1
    cfg = load_config(config_path)
    from dataclasses import asdict
    print(json.dumps(asdict(cfg), indent=2, default=str))
    return 0


def cmd_model_status(args: argparse.Namespace) -> int:
    from .compressor import model_status
    status = model_status()
    print(json.dumps(status, indent=2, default=str))
    return 0


def cmd_model_download(args: argparse.Namespace) -> int:
    from .compressor import is_available, download_model
    if not is_available():
        print("error: model backend not installed. Run: pip install mto[model]", file=sys.stderr)
        return 1
    print("Downloading model to local cache...")
    path = download_model()
    print(f"Model cached at: {path}")
    return 0


def cmd_proxy(args: argparse.Namespace) -> int:
    """Run command, capture output, compress it, print compressed version."""
    import subprocess
    from .output_filters import filter_output
    from .tokenizer import estimate_tokens

    argv = _strip_remainder_separator(args.argv)
    if not argv:
        print("error: no command provided", file=sys.stderr)
        return 1

    command_name = Path(argv[0]).name
    cmd_args = argv[1:]

    try:
        completed = subprocess.run(
            argv, text=True, capture_output=True, check=False,
        )
    except FileNotFoundError:
        print(f"error: command not found: {argv[0]}", file=sys.stderr)
        return 127

    output = (completed.stdout or "") + (completed.stderr or "")

    if args.raw or not output:
        sys.stdout.write(completed.stdout or "")
        sys.stderr.write(completed.stderr or "")
        return completed.returncode

    compressed = filter_output(command_name, cmd_args, output, completed.returncode)
    sys.stdout.write(compressed)
    if not compressed.endswith("\n"):
        sys.stdout.write("\n")
    return completed.returncode


def _args_or_stdin(parts: list[str]) -> str:
    if parts:
        return " ".join(parts)
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return ""


def _remainder_to_text(parts: list[str]) -> str:
    parts = _strip_remainder_separator(parts)
    return " ".join(parts)


def _strip_remainder_separator(parts: list[str]) -> list[str]:
    if parts and parts[0] == "--":
        return parts[1:]
    return parts


def _split_wrap(value: str) -> list[str]:
    return [item.strip() for item in value.replace(",", " ").split() if item.strip()]


def _resolve_level(cli_level: str | None) -> OptimizationLevel:
    """Resolve optimization level: CLI flag > config > default."""
    if cli_level:
        return OptimizationLevel(cli_level)
    cfg = load_config()
    return OptimizationLevel(cfg.optimization_level)


def cmd_install_shims(args: argparse.Namespace) -> int:
    from .shims import install_shims, get_shims_env, SHIM_DIR

    shim_dir = Path(args.dir) if args.dir else None
    commands = [c.strip() for c in args.commands.split(",")] if args.commands else None
    created = install_shims(commands=commands, shim_dir=shim_dir)
    target = shim_dir or SHIM_DIR
    print(f"installed {len(created)} shims in {target}")
    print(f"activate in agent sessions: eval \"$(mto shims-env)\"")
    print("your shell rc files are NOT modified")
    return 0


def cmd_uninstall_shims(args: argparse.Namespace) -> int:
    from .shims import uninstall_shims

    shim_dir = Path(args.dir) if args.dir else None
    removed = uninstall_shims(shim_dir=shim_dir)
    print(f"removed {len(removed)} shims")
    return 0


def cmd_shims_env(args: argparse.Namespace) -> int:
    from .shims import get_shims_env

    shim_dir = Path(args.dir) if args.dir else None
    print(get_shims_env(shim_dir))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
