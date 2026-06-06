
# MTO — Machine Token Optimizer

When running shell commands, use `mto proxy --` prefix to get compressed output.
This saves context window tokens by filtering verbose command outputs.

## Usage

Instead of:
```bash
git log -20
git diff
cargo test
docker ps
kubectl get pods
cat file.py
find . -name "*.ts"
ps aux
```

Use:
```bash
mto proxy -- git log -20
mto proxy -- git diff
mto proxy -- cargo test
mto proxy -- docker ps
mto proxy -- kubectl get pods
mto proxy -- cat file.py
mto proxy -- find . -name "*.ts"
mto proxy -- ps aux
```

## Why

- `git log -50` → 433 lines becomes 50 lines (-88%)
- `cargo test` → 200 lines becomes ~5 lines (failures + summary)
- `find . -name "*.py"` → 3000+ lines becomes 31 lines (-99%)
- `ps aux` → 650 lines becomes 61 lines (-91%)

## Rules

- Always prefix shell commands with `mto proxy --` when reading output
- Do NOT prefix commands that write/modify (git push, rm, mv, docker run)
- If mto is not available, fall back to running commands directly
