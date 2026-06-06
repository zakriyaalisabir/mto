#!/usr/bin/env bash
# Example: Output proxy compression (compresses command outputs)
# Run: bash examples/output_proxy.sh

set -e

echo "╔══════════════════════════════════════════════╗"
echo "║  mto Output Proxy Examples                   ║"
echo "╚══════════════════════════════════════════════╝"
echo

echo "── git log: verbose → one-line-per-commit ──"
RAW=$(git log -10 2>/dev/null | wc -l | tr -d ' ')
PROXY=$(mto proxy -- git log -10 2>/dev/null | wc -l | tr -d ' ')
echo "  Raw: ${RAW} lines → Proxied: ${PROXY} lines"
echo "  Output:"
mto proxy -- git log -10 2>/dev/null | head -5
echo "  ..."
echo

echo "── git show HEAD: strips metadata, keeps diff ──"
RAW=$(git show HEAD 2>/dev/null | wc -l | tr -d ' ')
PROXY=$(mto proxy -- git show HEAD 2>/dev/null | wc -l | tr -d ' ')
echo "  Raw: ${RAW} lines → Proxied: ${PROXY} lines"
echo

echo "── docker ps: whitespace compacted ──"
if command -v docker >/dev/null 2>&1; then
  echo "  Raw:"
  docker ps 2>/dev/null | head -3
  echo "  Proxied:"
  mto proxy -- docker ps 2>/dev/null | head -3
else
  echo "  (docker not available, skipping)"
fi
echo

echo "── Explicit proxy usage ──"
echo "  mto proxy -- git status"
mto proxy -- git status 2>/dev/null
echo

echo "── Raw passthrough (--raw flag) ──"
echo "  mto proxy --raw -- git log -3"
mto proxy --raw -- git log -3 2>/dev/null | wc -l | xargs -I{} echo "  {} lines (uncompressed)"
