#!/usr/bin/env bash
# Example: Side-by-side comparison of raw vs mto-compressed
# Run: bash examples/compare.sh

set -e

echo "╔══════════════════════════════════════════════╗"
echo "║  mto Before/After Comparison                 ║"
echo "╚══════════════════════════════════════════════╝"
echo

compare() {
  local label="$1"
  shift
  local raw proxy
  raw=$("$@" 2>&1 | wc -l | tr -d ' ')
  proxy=$(mto proxy -- "$@" 2>&1 | wc -l | tr -d ' ')
  local saved=$((raw - proxy))
  local pct=0
  [ "$raw" -gt 0 ] && pct=$(( (saved * 100) / raw ))
  printf "  %-30s %4s lines → %4s lines  (-%d%%)\n" "$label" "$raw" "$proxy" "$pct"
}

echo "Command Output Compression:"
echo "────────────────────────────────────────────────────────────────"
compare "git log -10" git log -10
compare "git log -50" git log -50
compare "git log --stat -5" git log --stat -5
compare "git show HEAD" git show HEAD
compare "git status" git status

if command -v docker >/dev/null 2>&1; then
  compare "docker ps" docker ps
fi

echo
echo "────────────────────────────────────────────────────────────────"
echo
echo "Input Prompt Compression:"
echo "────────────────────────────────────────────────────────────────"

input_compare() {
  local label="$1"
  local text="$2"
  local raw_tokens proxy_tokens
  raw_tokens=$(mto optimize --level conservative --json "$text" | python3 -c "import sys,json;print(json.load(sys.stdin)['input_token_estimate'])")
  proxy_tokens=$(mto optimize --level aggressive --json "$text" | python3 -c "import sys,json;print(json.load(sys.stdin)['optimized_token_estimate'])")
  local saved=$((raw_tokens - proxy_tokens))
  local pct=0
  [ "$raw_tokens" -gt 0 ] && pct=$(( (saved * 100) / raw_tokens ))
  printf "  %-30s %3s tokens → %3s tokens (-%d%%)\n" "$label" "$raw_tokens" "$proxy_tokens" "$pct"
}

input_compare "Verbose help request" "Please please can you help me fix this issue. I keep getting this error over and over again. I don't know what to do. Nothing works. Can you please explain what is wrong."
input_compare "Redundant debug ask" "I really need help with this. I have been stuck on this for hours. Can you please explain what is wrong and give me the fix command. Any help would be greatly appreciated. Thanks in advance."
input_compare "Short clean prompt" "Fix the TypeError in main.py"

echo
echo "Done. Run 'mto stats' to see cumulative savings."
