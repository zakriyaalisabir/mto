#!/usr/bin/env bash
# Example: Input compression across optimization levels
# Run: bash examples/input_compression.sh

set -e

echo "╔══════════════════════════════════════════════╗"
echo "║  mto Input Compression Examples              ║"
echo "╚══════════════════════════════════════════════╝"
echo

INPUT="Please please can you help me fix this issue. I keep getting this error over and over again. I don't know what to do. Nothing works. Can you please explain what is wrong and give me the correct command to fix it. I have been stuck on this for hours. Any help would be greatly appreciated. Thanks in advance."

echo "INPUT ($(($(echo "$INPUT" | wc -c))) chars):"
echo "  $INPUT"
echo

echo "── Conservative ──"
mto optimize --level conservative "$INPUT"
echo
echo "── Moderate ──"
mto optimize --level moderate "$INPUT"
echo
echo "── Aggressive ──"
mto optimize --level aggressive "$INPUT"
echo

echo "── Token savings (aggressive, JSON) ──"
mto optimize --level aggressive --json "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f\"  Input tokens:  {d['input_token_estimate']}\")
print(f\"  Output tokens: {d['optimized_token_estimate']}\")
print(f\"  Saved:         {d['token_savings']} ({d['token_savings_percent']:.0f}%)\")
"

echo
echo "── Safety: code blocks preserved ──"
mto optimize --level aggressive 'Refactor this function please please.
```python
def add(a, b):
    return a + b
```'

echo
echo "── Safety: paths and errors preserved ──"
mto optimize --level aggressive "Fix the ValueError: bad config in /tmp/app/main.py line 42. Please help me."

echo
echo "── Safety: shell commands never modified ──"
mto optimize --level aggressive "git push origin main"

echo
echo "── MTO_DISABLED=1 bypasses compression ──"
MTO_DISABLED=1 mto optimize "this text passes through unchanged"
