# Machine Shell Token Optimizer (`mto`)

`mto` is a shell-native, model-independent command observer and local token optimizer for `bash` and `zsh`.

It is **not** an LLM agent, does **not** call any model, and does **not** depend on Codex, Cairo, Claude, OpenAI, or any other AI runtime.

It integrates directly with your shell and gives you two safe behaviors:

1. **Observe all interactive shell commands** through bash/zsh hooks and store redacted local metadata in SQLite.
2. **Optimize text payloads only when explicitly invoked or when selected commands are wrapped** through `mto exec`.

Normal shell commands are preserved unchanged by default.

---

## Why this design

Shell commands do not normally consume LLM tokens by themselves. Tokens matter when text is sent into an AI CLI, prompt-driven command tool, coding assistant, or any prompt-consuming program.

Therefore `mto` separates the system into two layers:

| Layer | Behavior | Rewrites commands? |
|---|---|---:|
| Shell observer | Logs every interactive command with classification, risk level, token estimate, status, and exit code | No |
| Text optimizer/wrapper | Optimizes AI-bound text payloads in argv or stdin for commands you explicitly wrap | Only text payloads, not executable command structure |

This keeps the shell integration direct while avoiding unsafe hidden command mutation.

---

## Install locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
mto init
```

Optional tokenizer support:

```bash
pip install -e ".[dev,tiktoken]"
```

`tiktoken` is optional and used only as a local tokenizer. No network/model call is made.

---

## Mount shell integration

### bash

```bash
mto install-shell --shell bash
source ~/.bashrc
```

Or use it for one session only:

```bash
eval "$(mto shell-hook bash)"
```

### zsh

```bash
mto install-shell --shell zsh
source ~/.zshrc
```

Or for one session only:

```zsh
eval "$(mto shell-hook zsh)"
```

---

## Unmount shell integration

Remove the managed block from your rc file:

```bash
mto uninstall-shell --shell bash
mto uninstall-shell --shell zsh
```

Disable it only in the current shell session:

```bash
mto_unmount
```

The generated shell hook defines `mto_unmount` for both bash and zsh.

---

## Observe every shell command

After mounting, every interactive command is observed by the shell hook.

Example:

```bash
git status
ls -lah
rm -rf ./build
```

`mto` stores redacted metadata in SQLite:

- raw command preview
- command hash
- shell name
- PID
- working directory
- token estimate
- input type
- risk level
- exit code
- command pattern usage

Dangerous commands are marked high risk but are **not** rewritten.

```bash
mto stats
```

JSON stats:

```bash
mto stats --json
```

---

## Optimize text manually

```bash
mto optimize "Please please help me fix this error and give me the command"
```

Example output:

```text
Task:
Diagnose the error and provide a fix.

Output:
1. Root cause
2. Fix command
3. Verification step
```

Classify without optimizing:

```bash
mto classify "rm -rf ./build"
```

---

## Wrap selected prompt-consuming CLIs

`mto` can wrap selected commands so their stdin/argv text is optimized before the command receives it.

This is still independent from any specific model or agent. The command can be anything.

Example one-session bash hook wrapping `fakeai` and `llm`:

```bash
eval "$(mto shell-hook bash --wrap fakeai,llm)"
```

Persistent bash install:

```bash
mto install-shell --shell bash --wrap fakeai,llm
source ~/.bashrc
```

Then calls like this go through `mto exec`:

```bash
llm "Please please summarize this repeated context repeated context repeated context"
```

The executable command name is preserved. Only a detected text payload is optimized.

---

## Explicit command runner

Run any command through `mto exec`:

```bash
mto exec -- echo "hello"
```

Dry-run a prompt-consuming CLI argument without executing it:

```bash
mto exec --optimize --dry-run -- fakeai "Please please help me fix this issue. Please please help me fix this issue."
```

Pipe stdin through local optimization:

```bash
cat huge-error.log | mto exec --optimize --dry-run -- fakeai
```

---

## Safety model

`mto` follows conservative rules:

- Never silently rewrites executable shell commands.
- Never executes dangerous commands on its own.
- Detects high-risk commands such as `rm -rf`, `sudo`, `chmod -R`, `dd`, `mkfs`, `curl | sh`, `kubectl delete`, `terraform destroy`, `docker system prune`, `git reset --hard`, `git clean -fd`, and SQL `DROP` statements.
- Redacts common secrets before SQLite storage.
- Preserves code blocks.
- Preserves file paths.
- Preserves final traceback error lines.
- Optimizes only AI-bound/prose/log/debug text when explicitly invoked or wrapped.

---

## SQLite storage

Default database:

```text
~/.local/share/mto/mto.sqlite3
```

Default config:

```text
~/.config/mto/config.json
```

Main tables:

- `shell_command_events`
- `command_patterns`
- `optimization_runs`
- `optimization_patterns`
- `optimization_feedback`
- `reusable_context`

SQLite FTS5 is attempted when available, but the tool works without it.

---

## Config

Create default config:

```bash
mto init
```

Example `~/.config/mto/config.json`:

```json
{
  "enabled": true,
  "observe_all_commands": true,
  "db_path": "/home/user/.local/share/mto/mto.sqlite3",
  "wrap_commands": [],
  "optimize_commands": {
    "codex": "argv_join",
    "cairo": "argv_join",
    "aider": "argv_join",
    "claude": "argv_join",
    "llm": "argv_join",
    "sgpt": "argv_join"
  },
  "store_full_text": false,
  "default_timeout_seconds": 300.0
}
```

Environment overrides:

```bash
export MTO_DB_PATH=/tmp/mto.sqlite3
export MTO_ENABLED=1
export MTO_OBSERVE_ALL=1
export MTO_WRAP_COMMANDS="llm fakeai"
```

---

## Development and tests

```bash
pip install -e ".[dev]"
pytest
```

The test suite includes:

- Unit tests for command classification.
- Unit tests for local prompt/log optimization.
- Secret redaction and SQLite logging tests.
- Feedback score update tests.
- Shell mount/unmount tests.
- Real bash subshell hook integration test.
- CLI dry-run integration test.

---

## Non-goals

`mto` does not:

- Replace your shell.
- Act as an LLM agent.
- Call a model.
- Transparently rewrite every command you type.
- Require cloud services.
- Store raw secrets.

It is a local shell layer for observation, classification, token estimation, safe local text optimization, and command usage analytics.
