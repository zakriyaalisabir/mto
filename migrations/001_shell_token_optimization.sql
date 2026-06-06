CREATE TABLE IF NOT EXISTS optimization_runs (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    input_hash TEXT NOT NULL,
    input_preview TEXT NOT NULL,
    optimized_preview TEXT NOT NULL,
    input_token_estimate INTEGER NOT NULL,
    optimized_token_estimate INTEGER NOT NULL,
    token_savings INTEGER NOT NULL,
    token_savings_percent REAL NOT NULL,
    input_type TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    command_name TEXT,
    was_optimized INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_optimization_runs_created_at ON optimization_runs(created_at);
CREATE INDEX IF NOT EXISTS idx_optimization_runs_input_type ON optimization_runs(input_type);
CREATE INDEX IF NOT EXISTS idx_optimization_runs_command_name ON optimization_runs(command_name);
CREATE TABLE IF NOT EXISTS optimization_patterns (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    pattern_hash TEXT NOT NULL UNIQUE,
    pattern_type TEXT NOT NULL,
    original_pattern_preview TEXT NOT NULL,
    optimized_pattern_preview TEXT NOT NULL,
    usage_count INTEGER NOT NULL DEFAULT 1,
    average_savings_percent REAL NOT NULL DEFAULT 0,
    success_score REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_optimization_patterns_pattern_type ON optimization_patterns(pattern_type);
CREATE TABLE IF NOT EXISTS reusable_context (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    key TEXT NOT NULL UNIQUE,
    summary TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '',
    token_estimate INTEGER NOT NULL DEFAULT 0,
    last_used_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_reusable_context_content_hash ON reusable_context(content_hash);
CREATE TABLE IF NOT EXISTS optimization_feedback (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    run_id TEXT NOT NULL,
    rating TEXT NOT NULL CHECK (rating IN ('good', 'bad')),
    notes TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(run_id) REFERENCES optimization_runs(id)
);
CREATE INDEX IF NOT EXISTS idx_optimization_feedback_run_id ON optimization_feedback(run_id);
CREATE TABLE IF NOT EXISTS shell_command_events (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    shell TEXT NOT NULL,
    pid INTEGER NOT NULL,
    cwd TEXT NOT NULL,
    command_hash TEXT NOT NULL,
    raw_command_preview TEXT NOT NULL,
    optimized_preview TEXT NOT NULL DEFAULT '',
    token_estimate INTEGER NOT NULL,
    input_type TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    was_modified INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'started',
    exit_code INTEGER
);
CREATE INDEX IF NOT EXISTS idx_shell_command_events_created_at ON shell_command_events(created_at);
CREATE INDEX IF NOT EXISTS idx_shell_command_events_pid_status ON shell_command_events(pid, status);
CREATE INDEX IF NOT EXISTS idx_shell_command_events_input_type ON shell_command_events(input_type);
CREATE INDEX IF NOT EXISTS idx_shell_command_events_risk_level ON shell_command_events(risk_level);
CREATE TABLE IF NOT EXISTS command_patterns (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    pattern_hash TEXT NOT NULL UNIQUE,
    command_pattern TEXT NOT NULL,
    command_name TEXT NOT NULL,
    usage_count INTEGER NOT NULL DEFAULT 1,
    average_token_estimate REAL NOT NULL DEFAULT 0,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_command_patterns_command_name ON command_patterns(command_name);
