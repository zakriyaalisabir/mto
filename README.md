# `mto` — Machine Token Optimizer

**Local prompt compressor for AI shell tools.** Reduces token cost on what you *send* to LLMs.

`mto` sits between you and your AI CLI tools (`codex`, `claude`, `llm`, `aider`, `sgpt`, `kiro-cli`). It observes your shell, detects when you're talking to an AI, and compresses your verbose human text into tight prompts — before they leave your machine.

Shell commands pass through unchanged. Only natural-language payloads get compressed.

```
You type:                                  What reaches the LLM:
─────────────────────────────────────────────────────────────────
codex "Please please help me fix           codex "Fix this recurring
this error over and over I don't           error. Provide fix command."
know what to do please explain
and give me the command"

git push origin main                  →    git push origin main (untouched)
```

---

## Install

**Requires Python 3.11+**

```bash
# One-line interactive setup
bash scripts/setup.sh
```

### From GitHub (pip)

```bash
pip install git+https://github.com/zakriyaalisabir/mto.git
mto model download
```

> If you get a Python version error, you're using your system Python. Use a compatible version:
> ```bash
> python3.11 -m pip install git+https://github.com/zakriyaalisabir/mto.git
> # or
> brew install python@3.13 && python3.13 -m pip install git+https://github.com/zakriyaalisabir/mto.git
> ```

### Lightweight install (no model, rule-based only)

```bash
pip install git+https://github.com/zakriyaalisabir/mto.git --no-deps
```

### From source

```bash
git clone https://github.com/zakriyaalisabir/mto.git && cd mto
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
mto init
mto model download
mto install-shell --shell zsh --wrap codex,claude,llm,aider,sgpt,kiro-cli
source ~/.zshrc
```

---

## Compression Levels

| Level | Savings | Method |
|-------|---------|--------|
| `conservative` | ~30% | Filler word removal |
| `moderate` | ~60% | + stop-phrase removal, clause dedup |
| `aggressive` | ~70%+ | + intent extraction, local model if available |

```bash
mto optimize --level aggressive "your verbose prompt here"
```

Default level is set in config or via `export MTO_OPTIMIZATION_LEVEL=aggressive`.

---

## What It Does vs. What It Doesn't

| Does | Doesn't |
|------|---------|
| Compress natural-language prompts before they reach AI CLIs | Filter or modify command *outputs* |
| Observe shell commands (metadata only, redacted) | Replace your shell or act as a proxy |
| Run a local model for semantic compression | Call any remote API or cloud service |
| Preserve code blocks, file paths, error messages | Touch executable shell commands |
| Store redacted analytics in local SQLite | Store raw secrets or full command text |

---

## Verification

```bash
# Classify input type and risk
mto classify "rm -rf /"
mto classify "Please help me fix this error"

# Compare compression levels
mto optimize "Please please help me fix this issue over and over"
mto optimize --level moderate "Please please help me fix this issue over and over"
mto optimize --level aggressive "Please please help me fix this issue over and over"

# Full metadata output
mto optimize --level aggressive --json "I really need help. Can you explain what is wrong?"

# Dry-run (shows what would happen, doesn't execute)
mto exec --optimize --dry-run -- codex "Please please help me fix this"

# Shell commands are never modified
mto optimize "git push origin main"

# Skip compression for one command
MTO_DISABLED=1 codex "leave this alone"

# Analytics
mto stats
mto stats --json
mto stats --reset

# Current config
mto config
mto status
mto model status
```

---

## Configuration

`~/.config/mto/config.json`

```bash
mto config            # show current
mto config --create   # create with defaults
```

```json
{
  "enabled": true,
  "observe_all_commands": true,
  "optimization_level": "aggressive",
  "wrap_commands": ["codex", "claude", "llm"],
  "optimize_commands": {
    "codex": "argv_join",
    "claude": "argv_join",
    "llm": "argv_join"
  },
  "history_days": 90,
  "tee_enabled": true,
  "tee_mode": "failures",
  "tee_max_files": 20,
  "exclude_commands": ["git rebase", "git cherry-pick", "docker exec"]
}
```

### Environment Variables

| Variable | Effect |
|----------|--------|
| `MTO_DISABLED=1` | Skip optimization for this single command |
| `MTO_ENABLED=0` | Disable globally |
| `MTO_OPTIMIZATION_LEVEL` | Override compression level |
| `MTO_WRAP_COMMANDS` | Override which tools are wrapped |
| `MTO_TEE_DIR` | Override failure output directory |
| `MTO_DB_PATH` | Override SQLite path |

### Failure Output Capture

When a wrapped command exits non-zero, the full output is saved locally:

```
[full output: ~/.local/share/mto/tee/1707753600_cargo_test.log]
```

Your AI tool can read the file for context without re-running.

### Excluding Commands

Commands that should never be rewritten:

```json
{ "exclude_commands": ["git rebase", "^curl", "docker exec"] }
```

Patterns match after stripping `sudo`/env prefixes. `^` prefix enables regex.

Single-command skip: `MTO_DISABLED=1 git rebase main`

### Per-Project Overrides

Drop `.mto/filters.json` in your project root:

```json
{ "exclude_commands": ["npm test", "cargo build"] }
```

Merges with global config.

---

## Shell Integration

```bash
# Install permanently
mto install-shell --shell zsh --wrap codex,claude,llm
source ~/.zshrc

# Remove
mto uninstall-shell --shell zsh

# Temporary session (no file changes)
eval "$(mto shell-hook zsh --wrap codex,claude,llm)"

# Disable for current session
mto_unmount
```

---

## Safety

- Shell commands are **never** rewritten or executed
- Dangerous commands are detected and flagged (`rm -rf`, `sudo`, `chmod -R`, `dd`, `mkfs`, `curl | sh`, `kubectl delete`, `terraform destroy`)
- Secrets are redacted before storage
- Code blocks, file paths, and error messages are preserved in compressed output
- Model output is rejected if it drops any critical content

---

## Development

```bash
pip install -e ".[dev]"
pytest
```

33 tests: classification, compression levels, secret redaction, shell hooks, CLI, model integration, SQLite storage.

---

## Architecture

See [docs/system-flow.md](docs/system-flow.md) for full mermaid diagrams of the system.

```
┌────────────────────────────────────────────────────┐
│  Your shell (zsh/bash)                              │
│                                                     │
│  preexec hook → observes every command (SQLite log) │
│                                                     │
│  Wrapped AI tools (codex, claude, llm, ...):        │
│    ┌──────────────────────────────────────────┐     │
│    │ 1. Extract text payload from args/stdin  │     │
│    │ 2. Classify (shell? prompt? code? log?)  │     │
│    │ 3. If AI-bound text:                     │     │
│    │    a. Rule-based compression             │     │
│    │    b. Local model compression (optional) │     │
│    │    c. Safety check (paths/code/errors)   │     │
│    │    d. Pick shortest safe candidate       │     │
│    │ 4. Execute real command with shorter text │     │
│    └──────────────────────────────────────────┘     │
│                                                     │
│  Non-wrapped commands: pass through unchanged       │
└────────────────────────────────────────────────────┘
```
