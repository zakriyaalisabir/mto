#!/usr/bin/env bash
# Example: Stress test — bulk commands raw vs mto proxy
# Simulates what an AI agent session does: many shell commands generating verbose output
# Run: bash examples/stress_test.sh

set -e

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  mto Stress Test: Agent Session Simulation               ║"
echo "║  Runs common dev commands and compares token usage        ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo

TOTAL_RAW=0
TOTAL_PROXY=0

measure() {
  local label="$1"
  shift
  local raw proxy
  raw=$("$@" 2>&1 | wc -l | tr -d ' ')
  proxy=$(mto proxy -- "$@" 2>&1 | wc -l | tr -d ' ')
  TOTAL_RAW=$((TOTAL_RAW + raw))
  TOTAL_PROXY=$((TOTAL_PROXY + proxy))
  printf "  %-40s %5s → %5s lines\n" "$label" "$raw" "$proxy"
}

echo "── File Operations ──"
measure "ls -la /" ls -la /
measure "ls -laR /usr/local/bin (recursive)" ls -la /usr/local/bin
measure "find . -name '*.py'" find . -name "*.py"
measure "cat README.md" cat README.md
echo

echo "── Git Operations ──"
measure "git log -30" git log -30
measure "git log --stat -10" git log --stat -10
measure "git log --oneline -50" git log --oneline -50
measure "git show HEAD" git show HEAD
measure "git status" git status
measure "git branch -a" git branch -a
measure "git stash list" git stash list
echo

echo "── System Info ──"
measure "env (all environment)" env
measure "ps aux" ps aux
if command -v docker >/dev/null 2>&1; then
  measure "docker ps -a" docker ps -a
  measure "docker images" docker images
fi
echo

echo "── Package/Dependency Info ──"
if command -v pip3 >/dev/null 2>&1; then
  measure "pip3 list" pip3 list
fi
if command -v brew >/dev/null 2>&1; then
  measure "brew list" brew list
fi
echo

echo "── Network ──"
if command -v curl >/dev/null 2>&1; then
  measure "curl -sI https://github.com" curl -sI https://github.com
fi
echo

echo "════════════════════════════════════════════════════════════"
SAVED=$((TOTAL_RAW - TOTAL_PROXY))
PCT=0
[ "$TOTAL_RAW" -gt 0 ] && PCT=$(( (SAVED * 100) / TOTAL_RAW ))
echo
echo "  TOTAL RAW OUTPUT:        ${TOTAL_RAW} lines"
echo "  TOTAL PROXIED OUTPUT:    ${TOTAL_PROXY} lines"
echo "  TOTAL SAVED:             ${SAVED} lines (-${PCT}%)"
echo
echo "  In a 30-min agent session running these commands 3-5x each,"
echo "  mto would save ~$((SAVED * 4)) lines of context window tokens."
echo
echo "════════════════════════════════════════════════════════════"
echo
echo "Run 'mto stats' to see cumulative savings."
