"""SQLite storage for command observations and optimization history."""

from __future__ import annotations

import hashlib
import re
import sqlite3
import uuid
from pathlib import Path

from .models import OptimizationResult, ShellCommandEvent
from .redaction import redact_secrets
from .tokenizer import estimate_tokens

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_MIGRATION_PATH = _PACKAGE_ROOT / "migrations" / "001_shell_token_optimization.sql"

_SCHEMA_SQL = """
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
"""


def default_db_path() -> Path:
    import os
    if os.environ.get("MTO_DB_PATH"):
        return Path(os.environ["MTO_DB_PATH"]).expanduser()
    return Path.home() / ".local" / "share" / "mto" / "mto.sqlite3"


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def preview(text: str, limit: int = 4096) -> str:
    redacted = redact_secrets(text).strip()
    if len(redacted) <= limit:
        return redacted
    return redacted[: limit - 32].rstrip() + "\n[preview truncated]"


class ShellTokenStorage:
    """Small SQLite data access layer."""

    def __init__(self, db_path: str | Path | None = None, *, initialize: bool = True) -> None:
        self.db_path = Path(db_path).expanduser() if db_path is not None else default_db_path()
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        if initialize:
            self.initialize()

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def initialize(self) -> None:
        migration_sql = _SCHEMA_SQL
        if _DEFAULT_MIGRATION_PATH.exists():
            migration_sql = _DEFAULT_MIGRATION_PATH.read_text(encoding="utf-8")
        self._conn.executescript(migration_sql)
        self._try_enable_fts()
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def _try_enable_fts(self) -> None:
        try:
            self._conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS reusable_context_fts USING fts5(key, summary, tags, content='reusable_context', content_rowid='rowid')"
            )
            self._conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS command_patterns_fts USING fts5(command_pattern, command_name, content='command_patterns', content_rowid='rowid')"
            )
        except sqlite3.OperationalError:
            pass

    def log_optimization_run(self, result: OptimizationResult) -> str:
        run_id = result.run_id or str(uuid.uuid4())
        result.run_id = run_id
        original = redact_secrets(result.original_text)
        optimized = redact_secrets(result.optimized_text)
        self._conn.execute(
            """
            INSERT INTO optimization_runs (
                id, input_hash, input_preview, optimized_preview,
                input_token_estimate, optimized_token_estimate,
                token_savings, token_savings_percent,
                input_type, risk_level, command_name, was_optimized, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                hash_text(original),
                preview(original),
                preview(optimized),
                result.input_token_estimate,
                result.optimized_token_estimate,
                result.token_savings,
                result.token_savings_percent,
                result.input_type,
                result.risk_level,
                result.command_name,
                int(result.was_optimized),
                result.status,
            ),
        )
        if result.was_optimized:
            self.upsert_optimization_pattern(result)
        self._conn.commit()
        return run_id

    def upsert_optimization_pattern(self, result: OptimizationResult) -> str:
        original = redact_secrets(result.original_text)
        optimized = redact_secrets(result.optimized_text)
        pattern_hash = hash_text(f"{result.input_type}:{self._shape(original)}")
        existing = self._conn.execute(
            "SELECT id, usage_count, average_savings_percent FROM optimization_patterns WHERE pattern_hash = ?",
            (pattern_hash,),
        ).fetchone()
        if existing:
            usage_count = int(existing["usage_count"]) + 1
            previous_average = float(existing["average_savings_percent"])
            average = previous_average + (result.token_savings_percent - previous_average) / usage_count
            self._conn.execute(
                """
                UPDATE optimization_patterns
                SET usage_count = ?, average_savings_percent = ?,
                    original_pattern_preview = ?, optimized_pattern_preview = ?
                WHERE pattern_hash = ?
                """,
                (usage_count, average, preview(original, 1024), preview(optimized, 1024), pattern_hash),
            )
            return str(existing["id"])
        pattern_id = str(uuid.uuid4())
        self._conn.execute(
            """
            INSERT INTO optimization_patterns (
                id, pattern_hash, pattern_type, original_pattern_preview,
                optimized_pattern_preview, usage_count, average_savings_percent, success_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pattern_id,
                pattern_hash,
                result.input_type,
                preview(original, 1024),
                preview(optimized, 1024),
                1,
                result.token_savings_percent,
                0.0,
            ),
        )
        return pattern_id

    def log_shell_event(
        self,
        *,
        raw_command: str,
        shell: str,
        pid: int,
        cwd: str,
        input_type: str,
        risk_level: str,
        was_modified: bool = False,
        optimized_preview: str = "",
    ) -> str:
        event_id = str(uuid.uuid4())
        redacted = redact_secrets(raw_command)
        token_estimate = estimate_tokens(redacted)
        self._conn.execute(
            """
            INSERT INTO shell_command_events (
                id, shell, pid, cwd, command_hash, raw_command_preview,
                optimized_preview, token_estimate, input_type, risk_level,
                was_modified, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'started')
            """,
            (
                event_id,
                shell,
                pid,
                cwd,
                hash_text(redacted),
                preview(redacted),
                preview(optimized_preview),
                token_estimate,
                input_type,
                risk_level,
                int(was_modified),
            ),
        )
        self._upsert_command_pattern(redacted, token_estimate)
        self._conn.commit()
        return event_id

    def complete_latest_shell_event(self, *, shell: str, pid: int, exit_code: int) -> str | None:
        row = self._conn.execute(
            """
            SELECT id FROM shell_command_events
            WHERE shell = ? AND pid = ? AND status = 'started'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (shell, pid),
        ).fetchone()
        if not row:
            return None
        event_id = str(row["id"])
        self._conn.execute(
            """
            UPDATE shell_command_events
            SET status = 'completed', completed_at = CURRENT_TIMESTAMP, exit_code = ?
            WHERE id = ?
            """,
            (exit_code, event_id),
        )
        self._conn.commit()
        return event_id

    def record_feedback(self, run_id: str, rating: str, notes: str = "") -> str:
        if rating not in {"good", "bad"}:
            raise ValueError("rating must be 'good' or 'bad'")
        feedback_id = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO optimization_feedback (id, run_id, rating, notes) VALUES (?, ?, ?, ?)",
            (feedback_id, run_id, rating, preview(notes, 512)),
        )
        run = self._conn.execute(
            "SELECT input_type, input_preview FROM optimization_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if run:
            pattern_hash = hash_text(f"{run['input_type']}:{self._shape(str(run['input_preview']))}")
            delta = 1.0 if rating == "good" else -2.0
            self._conn.execute(
                "UPDATE optimization_patterns SET success_score = success_score + ? WHERE pattern_hash = ?",
                (delta, pattern_hash),
            )
        self._conn.commit()
        return feedback_id

    def historical_success_bonus(self, input_type: str) -> float:
        row = self._conn.execute(
            "SELECT COALESCE(AVG(success_score), 0) AS bonus FROM optimization_patterns WHERE pattern_type = ?",
            (input_type,),
        ).fetchone()
        if not row:
            return 0.0
        return max(-15.0, min(15.0, float(row["bonus"] or 0.0)))

    def stats(self) -> dict[str, float | int | list[dict[str, object]]]:
        opt = self._conn.execute(
            """
            SELECT COUNT(*) AS runs,
                   COALESCE(SUM(token_savings), 0) AS total_token_savings,
                   COALESCE(AVG(token_savings_percent), 0) AS avg_savings_percent,
                   COALESCE(SUM(was_optimized), 0) AS optimized_runs
            FROM optimization_runs
            """
        ).fetchone()
        shell = self._conn.execute(
            """
            SELECT COUNT(*) AS shell_events,
                   COALESCE(SUM(token_estimate), 0) AS observed_token_estimate,
                   COALESCE(SUM(CASE WHEN risk_level = 'high' THEN 1 ELSE 0 END), 0) AS high_risk_events
            FROM shell_command_events
            """
        ).fetchone()
        top_rows = self._conn.execute(
            """
            SELECT command_name, usage_count, average_token_estimate
            FROM command_patterns
            ORDER BY usage_count DESC, command_name ASC
            LIMIT 10
            """
        ).fetchall()
        return {
            "optimization_runs": int(opt["runs"]),
            "optimized_runs": int(opt["optimized_runs"]),
            "total_token_savings": int(opt["total_token_savings"]),
            "avg_savings_percent": float(opt["avg_savings_percent"]),
            "shell_events": int(shell["shell_events"]),
            "observed_token_estimate": int(shell["observed_token_estimate"]),
            "high_risk_events": int(shell["high_risk_events"]),
            "top_commands": [
                {
                    "command_name": str(row["command_name"]),
                    "usage_count": int(row["usage_count"]),
                    "average_token_estimate": float(row["average_token_estimate"]),
                }
                for row in top_rows
            ],
        }

    def _upsert_command_pattern(self, redacted_command: str, token_estimate: int) -> None:
        pattern = self._command_pattern(redacted_command)
        if not pattern:
            return
        command_name = pattern.split()[0]
        pattern_hash = hash_text(pattern)
        existing = self._conn.execute(
            "SELECT usage_count, average_token_estimate FROM command_patterns WHERE pattern_hash = ?",
            (pattern_hash,),
        ).fetchone()
        if existing:
            usage = int(existing["usage_count"]) + 1
            previous = float(existing["average_token_estimate"])
            average = previous + (token_estimate - previous) / usage
            self._conn.execute(
                """
                UPDATE command_patterns
                SET usage_count = ?, average_token_estimate = ?, last_seen_at = CURRENT_TIMESTAMP
                WHERE pattern_hash = ?
                """,
                (usage, average, pattern_hash),
            )
            return
        self._conn.execute(
            """
            INSERT INTO command_patterns (id, pattern_hash, command_pattern, command_name, usage_count, average_token_estimate)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (str(uuid.uuid4()), pattern_hash, pattern, command_name, float(token_estimate)),
        )

    def _command_pattern(self, command: str) -> str:
        command = command.strip()
        if not command:
            return ""
        parts = command.split()
        if not parts:
            return ""
        normalized: list[str] = []
        for part in parts[:8]:
            if re.match(r"^-", part):
                normalized.append(part)
            elif "/" in part or re.search(r"\d", part):
                normalized.append("<arg>")
            elif len(part) > 40:
                normalized.append("<long>")
            else:
                normalized.append(part)
        return " ".join(normalized)

    def _shape(self, text: str) -> str:
        shaped = re.sub(r"```[\s\S]*?```", "<code_block>", text)
        shaped = re.sub(r"/[\w./:@+-]+", "<path>", shaped)
        shaped = re.sub(r"\b\d+\b", "<num>", shaped)
        shaped = re.sub(r"\s+", " ", shaped).strip().lower()
        return shaped[:512]
