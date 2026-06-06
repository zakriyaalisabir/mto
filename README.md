# Machine Shell Token Optimizer (`mto`)

`mto` is a shell-native, model-independent command observer and local token optimizer for `bash` and `zsh`.

It integrates directly with your shell and gives you two behaviors:

1. **Observe all interactive shell commands** through bash/zsh hooks and store redacted local metadata in SQLite.
2. **Optimize text payloads** sent to AI CLIs (codex, claude, llm, aider, sgpt, kiro-cli) — automatically compressing verbose prompts before they reach the model.

Normal shell commands are preserved unchanged. Only AI-bound text gets compressed.

---

## Quick Setup (Interactive)

One command to set up everything:

```bash
bash scripts/setup.sh
```

This interactively asks you:
- Which shell (bash/zsh)
- Which AI tools to wrap (codex, claude, llm, aider, sgpt, kiro-cli, etc.)
- Optimization level (conservative/moderate/aggressive)
- Whether to install the local compression model (~353MB)

Then reload your shell:

```bash
source ~/.zshrc   # or source ~/.bashrc
```

---

## Manual Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
mto init
mto install-shell --shell zsh --wrap codex,claude,llm,aider,sgpt,kiro-cli
source ~/.zshrc
```

Optional local model (enables ML-powered compression in moderate/aggressive mode):

```bash
pip install -e ".[model]"
mto model download
```

---

## How It Works

After setup, your shell operates normally — but wrapped AI tools get their text payloads compressed automatically:

```
You type:                                         What the AI tool receives:
────────────────────────────────────────────────────────────────────────────────
codex "Please please help me fix this             codex "Fix this recurring
error over and over I don't know what             error. Provide fix command."
to do please explain and give me the
command"

git push origin main                              git push origin main (unchanged)
```

---

## Optimization Levels

```bash
mto optimize --level conservative "verbose text"   # ~30% savings, safe
mto optimize --level moderate "verbose text"       # ~60% savings
mto optimize --level aggressive "verbose text"     # ~70%+ savings, uses model if available
```

Set default level in `~/.config/mto/config.json` or via env:

```bash
export MTO_OPTIMIZATION_LEVEL=aggressive
```

---

## Test Commands

```bash
# Run test suite
pytest

# Classify a command (shows type + risk)
mto classify "rm -rf /"
mto classify "Please help me fix this error"

# Optimize text at each level
mto optimize "Please please help me fix this issue over and over"
mto optimize --level moderate "Please please help me fix this issue over and over"
mto optimize --level aggressive "Please please help me fix this issue over and over"

# JSON output with full metadata
mto optimize --level aggressive --json "I really need help. Can you explain what is wrong?"

# Dry-run exec (shows what would happen, doesn't execute)
mto exec --optimize --dry-run -- codex "Please please help me fix this"

# Shell command preserved (never optimized)
mto optimize "git push origin main"

# Check model status
mto model status

# View stats
mto stats
mto stats --json

# Check active config
mto status
```

---

## Reset Stats

Clear all observation and optimization history:

```bash
mto stats --reset
```

This deletes all data from the SQLite database (shell events, optimization runs, patterns, feedback) while keeping the database file and config intact.

---

## Shell Hook Management

```bash
# Install (persistent, survives shell restarts)
mto install-shell --shell zsh --wrap codex,claude,llm
source ~/.zshrc

# Uninstall
mto uninstall-shell --shell zsh

# One-session only (no file modification)
eval "$(mto shell-hook zsh --wrap codex,claude,llm)"

# Disable for current session
mto_unmount
```

---

## Local Model

The optional local model uses `llama-cpp-python` with a quantized Qwen2-0.5B GGUF (~353MB). It runs entirely offline with no API calls.

```bash
pip install -e ".[model]"    # installs llama-cpp-python + huggingface-hub
mto model download           # downloads model to ~/.local/share/mto/models/
mto model status             # verify
```

The model activates automatically in `moderate` and `aggressive` modes as an additional compression candidate. If its output drops critical content (code blocks, paths, errors), the rule-based result is used instead.

---

## Safety Model

- Never silently rewrites executable shell commands
- Never executes dangerous commands on its own
- Detects high-risk commands (`rm -rf`, `sudo`, `chmod -R`, `dd`, `mkfs`, `curl | sh`, `kubectl delete`, `terraform destroy`, etc.)
- Redacts secrets before SQLite storage
- Preserves code blocks, file paths, and error lines in optimized output
- Model output rejected if it drops any critical content

---

## Config

Default config: `~/.config/mto/config.json`

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
  }
}
```

Environment overrides:

```bash
export MTO_ENABLED=1
export MTO_OPTIMIZATION_LEVEL=aggressive
export MTO_WRAP_COMMANDS="codex claude llm aider"
export MTO_DB_PATH=/tmp/mto.sqlite3
```

---

## Development

```bash
pip install -e ".[dev]"
pytest
```

33 tests covering: classification, optimization levels, secret redaction, shell hooks, CLI integration, model integration, and SQLite storage.

---

## Non-goals

`mto` does not:

- Replace your shell
- Act as an LLM agent
- Call a remote model/API
- Transparently rewrite executable commands
- Require cloud services
- Store raw secrets
