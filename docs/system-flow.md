# System Flow

## Overview

mto operates in two directions: compressing **inputs** (your prompts to AI tools) and compressing **outputs** (command results back to the agent).

## Full System Flow

```mermaid
flowchart TD
    User[You type a command] --> Hook[Shell Hook<br>preexec/precmd]
    Hook --> Classify{Classify input}
    
    Classify -->|AI tool<br>codex, claude, llm| InputPath[Input Compression Path]
    Classify -->|Shell command<br>git, docker, etc| OutputPath[Output Proxy Path]
    Classify -->|Plain command<br>cd, echo, etc| Passthrough[Pass through unchanged]
    
    InputPath --> Extract[Extract text payload<br>from args/stdin]
    Extract --> RuleCompress[Rule-based compression<br>filler removal, dedup, stop-phrases]
    RuleCompress --> ModelCompress{Local model<br>available?}
    ModelCompress -->|Yes| LLM[Qwen2-0.5B GGUF<br>few-shot compression]
    ModelCompress -->|No| Pick
    LLM --> Pick[Pick shortest safe candidate]
    Pick --> Safety{Drops code/paths<br>/errors?}
    Safety -->|Yes, reject| UseRule[Use rule-based result]
    Safety -->|No, safe| UseWinner[Use best candidate]
    UseRule --> Execute[Execute AI tool<br>with compressed prompt]
    UseWinner --> Execute
    
    OutputPath --> RunCmd[Run command<br>capture stdout/stderr]
    RunCmd --> Filter[Apply output filter<br>per command type]
    Filter --> Return[Return compressed output<br>to agent context]
    
    Passthrough --> Log[Log to SQLite<br>redacted metadata]
    Execute --> Log
    Return --> Log
```

## Input Compression Pipeline

```mermaid
flowchart LR
    Raw[Verbose prompt<br>90 tokens] --> Filler[Remove filler<br>please please, can you]
    Filler --> Stop[Remove stop phrases<br>I dont know what to do]
    Stop --> Dedup[Clause dedup<br>repeated intent]
    Dedup --> Clean[Clean fragments<br>capitalize, fix punctuation]
    Clean --> Model{Model<br>available?}
    Model -->|Yes| Compress[Model compression<br>paraphrase]
    Model -->|No| Best
    Compress --> Best[Best candidate<br>29 tokens]
```

## Output Proxy Pipeline

```mermaid
flowchart LR
    Cmd[git log -50<br>433 lines] --> Run[Execute real command]
    Run --> Detect[Detect command type]
    Detect --> Filter[Apply filter]
    Filter --> Out[Compressed output<br>50 lines]
    
    style Cmd fill:#f96
    style Out fill:#6f9
```

## Per-Command Output Filters

```mermaid
flowchart TD
    Command[mto proxy -- cmd] --> Route{Command?}
    
    Route -->|git log| GL[Convert to one-line-per-commit<br>strip author/date/body]
    Route -->|git show/diff| GD[Keep diff headers + changes<br>strip context lines]
    Route -->|git push/commit| GA[Collapse to ok + hash]
    Route -->|cargo test / pytest| T[Show failures only + summary]
    Route -->|docker ps| D[Compact whitespace]
    Route -->|docker logs| DL[Dedup repeated lines]
    Route -->|kubectl| K[Truncate to 30 lines]
    Route -->|grep/find| GR[Cap at 30 matches]
    Route -->|build/lint| B[Errors only on success<br>full on failure]
    Route -->|unknown| Gen[Generic: dedup + truncate 60 lines]
```

## Shell Hook Architecture

```mermaid
sequenceDiagram
    participant User
    participant Shell as zsh/bash
    participant Hook as mto preexec
    participant SQLite
    participant AI as AI Tool (codex)
    
    User->>Shell: codex "fix this please please"
    Shell->>Hook: preexec observes command
    Hook->>SQLite: log event (redacted)
    Hook->>AI: mto exec → compress "fix this" → codex "Fix this."
    AI-->>Shell: response
    Shell->>Hook: precmd records exit code
    Hook->>SQLite: complete event
    Shell-->>User: show response
```

## Agent Session with Proxy

```mermaid
sequenceDiagram
    participant Agent as AI Agent (codex session)
    participant MTO as mto proxy
    participant Cmd as Real command
    participant Context as Agent Context
    
    Agent->>MTO: git log -50
    MTO->>Cmd: execute git log -50
    Cmd-->>MTO: 433 lines raw output
    MTO->>MTO: filter → 50 lines (one per commit)
    MTO-->>Context: 50 lines (saved 383 lines)
    
    Agent->>MTO: cargo test
    MTO->>Cmd: execute cargo test
    Cmd-->>MTO: 200 lines (15 tests)
    MTO->>MTO: filter → failures + summary
    MTO-->>Context: 3 lines "PASSED: 15/15"
```
