# Changelog

## [0.2.0] - 2026-06-06

### Added

- **Optimization Levels** — `conservative`, `moderate`, `aggressive` via `--level` flag and config
- **Aggressive compression** — expanded filler patterns, stop-phrase removal, clause deduplication (keyword-bag overlap)
- **Local model compressor** — optional Qwen2-0.5B GGUF via `llama-cpp-python` for semantic compression
  - `mto model download` / `mto model status`
  - Few-shot completion prompt for paraphrase compression
  - Auto-candidate alongside rule-based output; best wins
- **Output proxy** — `mto proxy -- <cmd>` runs command and compresses output
  - Per-command filters: git, docker, kubectl, cargo, npm, pytest, go, eslint, ruff, aws, curl
  - Generic fallback: dedup repeated lines + truncation
  - `mto_agent` shell function activates proxy for dev commands in agent sessions
- **Config management** — `mto config` / `mto config --create`
- **Tee system** — saves full output to `~/.local/share/mto/tee/` on failure
- **Exclude commands** — `exclude_commands` config with regex support (`^curl`)
- **Per-project filters** — `.mto/filters.json` merges with global config
- **History retention** — `history_days` with auto-cleanup (default 90 days)
- **Stats reset** — `mto stats --reset`
- **Audit** — `mto audit --risk high` reviews dangerous commands from SQLite
- **MTO_DISABLED=1** — skip optimization for single command
- **Interactive setup** — `bash scripts/setup.sh` (detects Python 3.11+, asks shell/tools/level/model)

### Changed

- Default optimization level changed to `aggressive`
- Model dependencies (`llama-cpp-python`, `huggingface-hub`) are now default install (not optional)
- Semantic risk penalty: code blocks and error lines get full penalty (never halved), pure prose gets reduced penalty in aggressive mode
- Shell hooks preserve user aliases — `mto_agent` wraps through alias redefinition, keeps flags like `--color`

### Fixed

- Double-period artifacts after filler removal
- Orphan sentence fragments after stop-phrase removal
- Regex backreference error in aggressive filler patterns
- `source ~/.zshrc` error when `grep`/`ls` have color aliases
- Setup script failing on system Python 3.9 (now auto-detects 3.11+)

## [0.1.0] - 2026-05-30

### Added

- Initial release
- Shell command observer (bash/zsh preexec/precmd hooks)
- Input classifier: shell commands, AI prompts, code, logs, dangerous commands
- Conservative rule-based optimizer (filler removal, dedup)
- SQLite storage with secret redaction
- CLI: `mto optimize`, `classify`, `exec`, `stats`, `feedback`, `init`, `shell-hook`, `install-shell`
- Shell hook generation for bash/zsh/sh
- 21 tests covering classification, optimization, redaction, hooks, CLI
