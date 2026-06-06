#!/usr/bin/env bash
set -euo pipefail

# Example: wrap selected prompt-consuming CLIs for this shell session only.
# Replace fakeai/llm with commands you actually want to pass through mto exec.
eval "$(mto shell-hook bash --wrap fakeai,llm)"

# fakeai "Please please summarize this repeated context repeated context repeated context"
