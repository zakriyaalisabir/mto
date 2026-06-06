#!/usr/bin/env bash
set -e

echo "╔══════════════════════════════════════════╗"
echo "║   mto - Shell Token Optimizer Setup      ║"
echo "╚══════════════════════════════════════════╝"
echo

# Detect shell
detect_shell() {
  if [ -n "$ZSH_VERSION" ]; then echo "zsh"
  elif [ -n "$BASH_VERSION" ]; then echo "bash"
  else basename "$SHELL"; fi
}

DEFAULT_SHELL=$(detect_shell)

read -p "Which shell do you use? [bash/zsh] ($DEFAULT_SHELL): " SHELL_CHOICE
SHELL_CHOICE=${SHELL_CHOICE:-$DEFAULT_SHELL}

if [[ "$SHELL_CHOICE" != "bash" && "$SHELL_CHOICE" != "zsh" ]]; then
  echo "error: unsupported shell '$SHELL_CHOICE'. Use bash or zsh."
  exit 1
fi

# Select AI tools to wrap
echo
echo "Which AI/LLM tools should mto optimize? (space-separated)"
echo "Common options: codex claude llm aider sgpt kiro-cli"
echo
read -p "Tools to wrap (or press Enter for none): " WRAP_TOOLS

# Optimization level
echo
echo "Optimization level:"
echo "  conservative - minimal filler removal (safe, ~30% savings)"
echo "  moderate     - filler + stop-phrases + dedup (~60% savings)"
echo "  aggressive   - maximum compression + local model (~70%+ savings)"
echo
read -p "Level? [conservative/moderate/aggressive] (aggressive): " LEVEL
LEVEL=${LEVEL:-aggressive}

# Install model?
INSTALL_MODEL="n"
if [[ "$LEVEL" == "moderate" || "$LEVEL" == "aggressive" ]]; then
  echo
  read -p "Install local compression model (~353MB download)? [y/N]: " INSTALL_MODEL
  INSTALL_MODEL=${INSTALL_MODEL:-n}
fi

echo
echo "─── Installing mto ───"

# Ensure we're in a compatible venv
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

# Find Python >= 3.11
find_python() {
  for cmd in python3.13 python3.12 python3.11 python3; do
    if command -v "$cmd" &>/dev/null; then
      version=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
      major=$(echo "$version" | cut -d. -f1)
      minor=$(echo "$version" | cut -d. -f2)
      if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
        echo "$cmd"
        return 0
      fi
    fi
  done
  return 1
}

PYTHON_CMD=$(find_python)
if [ -z "$PYTHON_CMD" ]; then
  echo "error: Python >= 3.11 is required but not found."
  echo
  echo "Install Python 3.11+ using one of:"
  echo "  brew install python@3.13       # macOS"
  echo "  sudo apt install python3.13    # Ubuntu/Debian"
  echo "  pyenv install 3.13.1           # pyenv"
  exit 1
fi

echo "Using: $PYTHON_CMD ($($PYTHON_CMD --version))"

if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtual environment..."
  "$PYTHON_CMD" -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
pip install -e ".[dev]" --quiet

echo "─── Initializing config ───"
mto init

# Set optimization level in config
CONFIG_PATH="$HOME/.config/mto/config.json"
if command -v python3 &>/dev/null; then
  python3 -c "
import json, pathlib
p = pathlib.Path('$CONFIG_PATH')
cfg = json.loads(p.read_text())
cfg['optimization_level'] = '$LEVEL'
p.write_text(json.dumps(cfg, indent=2) + '\n')
"
fi

# Install shell hook
echo "─── Installing $SHELL_CHOICE hook ───"
if [ -n "$WRAP_TOOLS" ]; then
  mto install-shell --shell "$SHELL_CHOICE" --wrap "$WRAP_TOOLS"
else
  mto install-shell --shell "$SHELL_CHOICE"
fi

# Install model if requested
if [[ "$INSTALL_MODEL" =~ ^[Yy] ]]; then
  echo "─── Installing model backend ───"
  pip install -e ".[model]" --quiet
  echo "─── Downloading model ───"
  mto model download
fi

echo "─── Installing agent shims ───"
mto install-shims
mto init --agent

echo
echo "╔══════════════════════════════════════════╗"
echo "║   ✓ Setup complete!                      ║"
echo "╚══════════════════════════════════════════╝"
echo
echo "Reload your shell:"
if [ "$SHELL_CHOICE" = "zsh" ]; then
  echo "  source ~/.zshrc"
else
  echo "  source ~/.bashrc"
fi
echo
echo "Verify:"
echo "  mto status"
echo "  mto stats"
echo "  mto model status"
