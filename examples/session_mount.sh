#!/usr/bin/env bash
set -euo pipefail

# One-session mount for bash.
eval "$(mto shell-hook bash)"

echo "mto shell integration active"
echo "run commands normally; inspect later with: mto stats"

# Current-session unmount:
# mto_unmount
