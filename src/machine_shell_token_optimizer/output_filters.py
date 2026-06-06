"""Output filters for command proxy mode.

Compresses stdout/stderr from common dev commands before they return
to the agent's context window. Each filter is keyed by command name and
applies domain-specific compression.
"""

from __future__ import annotations

import re


def filter_output(command_name: str, args: list[str], output: str, exit_code: int) -> str:
    """Apply the best filter for the given command. Returns compressed output."""
    if not output or len(output) < 100:
        return output

    full_cmd = " ".join([command_name] + args)

    # Route to specific filter
    if command_name == "git":
        sub = args[0] if args else ""
        if sub == "status":
            return _filter_git_status(output)
        if sub == "log":
            return _filter_git_log(output)
        if sub == "diff":
            return _filter_git_diff(output)
        if sub in ("push", "pull", "fetch", "add", "commit"):
            return _filter_git_action(sub, output, exit_code)
    if command_name in ("cargo", "npm", "pnpm", "yarn") and args and args[0] == "test":
        return _filter_test_output(output, exit_code)
    if command_name == "pytest" or (command_name == "python" and "-m" in args and "pytest" in args):
        return _filter_test_output(output, exit_code)
    if command_name in ("go") and args and args[0] == "test":
        return _filter_test_output(output, exit_code)
    if command_name in ("jest", "vitest", "mocha"):
        return _filter_test_output(output, exit_code)
    if command_name == "docker" and args:
        return _filter_docker(args[0], output)
    if command_name == "kubectl":
        return _filter_kubectl(args, output)
    if command_name in ("ls", "find", "tree"):
        return _filter_file_listing(output)
    if command_name in ("cat", "head", "tail", "bat"):
        return _filter_file_read(output)
    if command_name in ("grep", "rg", "ag"):
        return _filter_grep(output)
    if command_name in ("cargo", "npm", "pnpm") and args and args[0] == "build":
        return _filter_build_output(output, exit_code)
    if command_name in ("eslint", "ruff", "clippy", "golangci-lint", "rubocop"):
        return _filter_lint(output)
    if command_name == "cargo" and args and args[0] == "clippy":
        return _filter_lint(output)
    if command_name == "aws":
        return _filter_aws(output)
    if command_name == "curl" or command_name == "wget":
        return _filter_network(output)

    # Generic: dedup repeated lines, truncate
    return _generic_filter(output)


def _filter_git_status(output: str) -> str:
    lines = output.strip().splitlines()
    if not lines:
        return output
    staged, modified, untracked = [], [], []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("new file:", "modified:", "deleted:", "renamed:")):
            staged.append(stripped)
        elif stripped.startswith("modified:"):
            modified.append(stripped)
        elif stripped and not stripped.startswith(("#", "On branch", "Your branch", "Changes", "Untracked", "  (use")):
            if "??" in line or line.startswith("??"):
                untracked.append(stripped.lstrip("? "))
            elif line.startswith(" M") or line.startswith("M "):
                modified.append(line.strip())
            else:
                modified.append(stripped)
    parts = []
    branch = next((l for l in lines if "On branch" in l), None)
    if branch:
        parts.append(branch.strip())
    if staged:
        parts.append(f"staged: {', '.join(staged[:10])}")
    if modified:
        parts.append(f"modified: {', '.join(modified[:10])}")
    if untracked:
        parts.append(f"untracked: {', '.join(untracked[:10])}")
    if not parts:
        return "clean"
    return "\n".join(parts)


def _filter_git_log(output: str) -> str:
    lines = output.strip().splitlines()
    # Already compact (one-line format) — pass through
    if all(len(l) < 120 for l in lines[:5]) and not any(l.startswith("Author:") for l in lines[:10]):
        return output
    # Verbose format: extract hash + first line of message into one-line-per-commit
    commits = []
    current_hash = ""
    for line in lines:
        if line.startswith("commit "):
            current_hash = line[7:14]  # short hash
        elif line.startswith("    ") and current_hash:
            msg = line.strip()
            if msg:  # first non-empty indented line is the subject
                commits.append(f"{current_hash} {msg}")
                current_hash = ""
    return "\n".join(commits) if commits else output


def _filter_git_diff(output: str) -> str:
    lines = output.strip().splitlines()
    if len(lines) <= 50:
        return output
    # Keep headers and change lines, skip context
    kept = []
    for line in lines:
        if line.startswith(("diff --", "---", "+++", "@@", "+", "-")):
            kept.append(line)
    if len(kept) > 80:
        kept = kept[:80]
        kept.append(f"[diff truncated, {len(lines)} total lines]")
    return "\n".join(kept)


def _filter_git_action(sub: str, output: str, exit_code: int) -> str:
    if exit_code == 0:
        # Extract key info
        lines = output.strip().splitlines()
        if sub == "push":
            branch = next((l for l in lines if "->" in l), None)
            return f"ok {branch.strip().split()[-1] if branch else 'pushed'}"
        if sub == "commit":
            sha = next((re.search(r"[0-9a-f]{7,}", l) for l in lines), None)
            return f"ok {sha.group(0) if sha else 'committed'}"
        return f"ok"
    return _truncate(output, 30)


def _filter_test_output(output: str, exit_code: int) -> str:
    lines = output.strip().splitlines()
    if exit_code == 0:
        # Just show summary
        summary = [l for l in lines[-10:] if re.search(r"pass|ok|success|\d+ test", l, re.IGNORECASE)]
        return "\n".join(summary) if summary else lines[-1] if lines else "ok"
    # Failed: show failures only
    failures = []
    for line in lines:
        if re.search(r"fail|error|panic|assert|FAILED", line, re.IGNORECASE):
            failures.append(line.strip())
    if failures:
        summary_line = next((l for l in lines[-5:] if re.search(r"\d+.*(?:pass|fail)", l, re.IGNORECASE)), "")
        result = failures[:30]
        if summary_line:
            result.append(summary_line.strip())
        return "\n".join(result)
    return _truncate(output, 40)


def _filter_docker(sub: str, output: str) -> str:
    if sub == "ps":
        lines = output.strip().splitlines()
        if not lines:
            return output
        # Keep header + compact each row
        header = lines[0]
        rows = [_compact_whitespace(l) for l in lines[1:]]
        return "\n".join([header] + rows[:20])
    if sub in ("logs", "compose"):
        return _dedup_lines(output, max_lines=40)
    return _truncate(output, 40)


def _filter_kubectl(args: list[str], output: str) -> str:
    lines = output.strip().splitlines()
    if len(lines) <= 30:
        return output
    return "\n".join(lines[:30]) + f"\n[{len(lines)} total lines]"


def _filter_file_listing(output: str) -> str:
    lines = output.strip().splitlines()
    if len(lines) <= 30:
        return output
    return "\n".join(lines[:30]) + f"\n[{len(lines)} total entries]"


def _filter_file_read(output: str) -> str:
    lines = output.strip().splitlines()
    if len(lines) <= 80:
        return output
    return "\n".join(lines[:40] + ["...", f"[{len(lines)} total lines]"] + lines[-10:])


def _filter_grep(output: str) -> str:
    lines = output.strip().splitlines()
    if len(lines) <= 30:
        return output
    return "\n".join(lines[:30]) + f"\n[{len(lines)} matches total]"


def _filter_build_output(output: str, exit_code: int) -> str:
    if exit_code == 0:
        lines = output.strip().splitlines()
        return lines[-1] if lines else "ok"
    # Show errors only
    lines = output.strip().splitlines()
    errors = [l for l in lines if re.search(r"error|Error|ERROR", l)]
    return "\n".join(errors[:20]) if errors else _truncate(output, 30)


def _filter_lint(output: str) -> str:
    lines = output.strip().splitlines()
    if len(lines) <= 30:
        return output
    # Keep error/warning lines
    issues = [l for l in lines if re.search(r"error|warning|warn|Error|Warning", l)]
    summary = [l for l in lines[-5:] if re.search(r"\d+", l)]
    result = issues[:30]
    result.extend(summary)
    return "\n".join(result)


def _filter_aws(output: str) -> str:
    # Truncate large JSON responses
    if len(output) > 2000:
        return output[:2000] + f"\n[truncated, {len(output)} bytes total]"
    return output


def _filter_network(output: str) -> str:
    # Strip progress bars, keep content
    lines = output.strip().splitlines()
    filtered = [l for l in lines if not re.match(r"^\s*\d+%|#|=+>", l)]
    return _truncate("\n".join(filtered), 50)


def _generic_filter(output: str) -> str:
    """Dedup + truncate for unknown commands."""
    output = _dedup_lines(output, max_lines=60)
    return _truncate(output, 60)


def _dedup_lines(output: str, max_lines: int = 60) -> str:
    lines = output.strip().splitlines()
    if len(lines) <= max_lines:
        return output
    kept: list[str] = []
    prev = None
    repeat = 0
    for line in lines:
        normalized = line.strip()
        if normalized == prev:
            repeat += 1
            continue
        if repeat > 0:
            kept.append(f"  [repeated {repeat + 1}x]")
        kept.append(line)
        prev = normalized
        repeat = 0
    if repeat > 0:
        kept.append(f"  [repeated {repeat + 1}x]")
    if len(kept) > max_lines:
        kept = kept[:max_lines]
        kept.append(f"[{len(lines)} total lines]")
    return "\n".join(kept)


def _truncate(output: str, max_lines: int) -> str:
    lines = output.strip().splitlines()
    if len(lines) <= max_lines:
        return output
    return "\n".join(lines[:max_lines]) + f"\n[{len(lines)} total lines]"


def _compact_whitespace(line: str) -> str:
    return re.sub(r"\s{2,}", "  ", line)
