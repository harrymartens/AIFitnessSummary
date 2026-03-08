"""Database layer for AIFitnessSummary.

Supports two backends selected by environment:
  - **PostgreSQL (Supabase)**: Set ``DATABASE_URL`` to your Supabase connection
    string (e.g. ``postgresql://postgres:...@db.xxx.supabase.co:5432/postgres``).
  - **SQLite (local)**: When ``DATABASE_URL`` is not set, falls back to a local
    SQLite file at ``DB_PATH`` (default ``fitness_memory.db``).

Usage:
    from db_client import get_db
    db = get_db()
"""

import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

_db_singleton: Optional["DatabaseClient"] = None

SQLITE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    primary_objective TEXT NOT NULL,
    body_comp_goal TEXT,
    target_weight_kg REAL,
    weight_change_kg_per_month REAL,
    target_steps_per_day INTEGER,
    target_sleep_hours REAL,
    target_workouts_per_week INTEGER,
    target_resting_hr INTEGER,
    target_vo2max REAL,
    timeline_weeks INTEGER,
    gym_sessions_per_week INTEGER,
    runs_per_week INTEGER,
    run_types TEXT,
    gym_description TEXT,
    gym_goals TEXT,
    running_goals TEXT,
    notes TEXT,
    is_active INTEGER DEFAULT 1,
    is_provisional INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    report_path TEXT,
    avg_steps REAL,
    avg_sleep_hours REAL,
    avg_resting_hr REAL,
    avg_hrv REAL,
    avg_stress REAL,
    avg_body_battery REAL,
    avg_spo2 REAL,
    avg_vo2max REAL,
    avg_weight_kg REAL,
    avg_body_fat_pct REAL,
    workouts_count INTEGER,
    total_volume_kg REAL,
    total_run_distance_km REAL
);

CREATE TABLE IF NOT EXISTS metrics_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL,
    FOREIGN KEY (review_id) REFERENCES reviews(id)
);

CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 2,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    resolution_note TEXT,
    FOREIGN KEY (review_id) REFERENCES reviews(id)
);

CREATE TABLE IF NOT EXISTS knowledge_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cache_key TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    query TEXT NOT NULL,
    result_text TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
"""

PG_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS goals (
    id SERIAL PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    primary_objective TEXT NOT NULL,
    body_comp_goal TEXT,
    target_weight_kg DOUBLE PRECISION,
    weight_change_kg_per_month DOUBLE PRECISION,
    target_steps_per_day INTEGER,
    target_sleep_hours DOUBLE PRECISION,
    target_workouts_per_week INTEGER,
    target_resting_hr INTEGER,
    target_vo2max DOUBLE PRECISION,
    timeline_weeks INTEGER,
    gym_sessions_per_week INTEGER,
    runs_per_week INTEGER,
    run_types TEXT,
    gym_description TEXT,
    gym_goals TEXT,
    running_goals TEXT,
    notes TEXT,
    is_active INTEGER DEFAULT 1,
    is_provisional INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reviews (
    id SERIAL PRIMARY KEY,
    period TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    report_path TEXT,
    avg_steps DOUBLE PRECISION,
    avg_sleep_hours DOUBLE PRECISION,
    avg_resting_hr DOUBLE PRECISION,
    avg_hrv DOUBLE PRECISION,
    avg_stress DOUBLE PRECISION,
    avg_body_battery DOUBLE PRECISION,
    avg_spo2 DOUBLE PRECISION,
    avg_vo2max DOUBLE PRECISION,
    avg_weight_kg DOUBLE PRECISION,
    avg_body_fat_pct DOUBLE PRECISION,
    workouts_count INTEGER,
    total_volume_kg DOUBLE PRECISION,
    total_run_distance_km DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS metrics_history (
    id SERIAL PRIMARY KEY,
    review_id INTEGER NOT NULL REFERENCES reviews(id),
    date TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS recommendations (
    id SERIAL PRIMARY KEY,
    review_id INTEGER NOT NULL REFERENCES reviews(id),
    category TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 2,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    resolution_note TEXT
);

CREATE TABLE IF NOT EXISTS knowledge_cache (
    id SERIAL PRIMARY KEY,
    cache_key TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    query TEXT NOT NULL,
    result_text TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
"""

KNOWLEDGE_CACHE_TTL_DAYS = 30


class DatabaseClient:
    """Persistence layer for AIFitnessSummary data.

    Transparently works with either SQLite or PostgreSQL (Supabase).
    """

    def __init__(self, db_path: Optional[str] = None, database_url: Optional[str] = None) -> None:
        self._pg = database_url is not None
        self._conn = None

        if self._pg:
            self._database_url = database_url
        else:
            self.db_path = db_path or "fitness_memory.db"

        self._init_schema()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_conn(self):
        """Return a lazily-created, reused connection."""
        if self._conn is None:
            if self._pg:
                import psycopg2
                import psycopg2.extras
                self._conn = psycopg2.connect(self._database_url)
                self._conn.autocommit = False
            else:
                self._conn = sqlite3.connect(self.db_path)
                self._conn.row_factory = sqlite3.Row
                self._conn.execute("PRAGMA foreign_keys = ON")
        return self._conn

    def _cursor(self):
        """Return a new cursor appropriate for the backend."""
        conn = self._get_conn()
        if self._pg:
            import psycopg2.extras
            return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        return conn.cursor()

    def _execute(self, sql: str, params=None):
        """Execute a single SQL statement, adapting placeholders for the backend."""
        cur = self._cursor()
        adapted = self._adapt_sql(sql)
        if params is None:
            cur.execute(adapted)
        else:
            cur.execute(adapted, params)
        return cur

    def _adapt_sql(self, sql: str) -> str:
        """Convert SQLite-style '?' placeholders to PostgreSQL '%s'."""
        if self._pg:
            return sql.replace("?", "%s")
        return sql

    def _fetchone(self, sql: str, params=None) -> Optional[dict]:
        """Execute and return a single row as dict, or None."""
        cur = self._execute(sql, params)
        row = cur.fetchone()
        if row is None:
            return None
        if self._pg:
            return dict(row)
        return dict(row)

    def _fetchall(self, sql: str, params=None) -> list[dict]:
        """Execute and return all rows as list of dicts."""
        cur = self._execute(sql, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]

    def _commit(self):
        """Commit the current transaction."""
        self._get_conn().commit()

    def _insert_returning_id(self, sql: str, params) -> int:
        """Insert a row and return the generated id.

        For PostgreSQL, appends RETURNING id. For SQLite, uses lastrowid.
        """
        if self._pg:
            sql = sql.rstrip().rstrip(";") + " RETURNING id"
            cur = self._execute(sql, params)
            row = cur.fetchone()
            self._commit()
            return row["id"]
        else:
            cur = self._execute(sql, params)
            self._commit()
            return cur.lastrowid

    def _init_schema(self) -> None:
        """Create all tables if they do not already exist, then migrate."""
        conn = self._get_conn()
        if self._pg:
            cur = conn.cursor()
            cur.execute(PG_SCHEMA_SQL)
            conn.commit()
        else:
            conn.executescript(SQLITE_SCHEMA_SQL)
            conn.commit()
        self._migrate_goals_table()

    def _migrate_goals_table(self) -> None:
        """Add new goal columns to existing databases if they are missing."""
        new_columns = [
            ("body_comp_goal", "TEXT"),
            ("weight_change_kg_per_month", "REAL" if not self._pg else "DOUBLE PRECISION"),
            ("gym_sessions_per_week", "INTEGER"),
            ("runs_per_week", "INTEGER"),
            ("run_types", "TEXT"),
            ("gym_description", "TEXT"),
            ("gym_goals", "TEXT"),
            ("running_goals", "TEXT"),
        ]
        conn = self._get_conn()
        for col_name, col_type in new_columns:
            try:
                self._execute(f"ALTER TABLE goals ADD COLUMN {col_name} {col_type}")
                conn.commit()
            except Exception:
                # Column already exists — expected on non-fresh databases
                if self._pg:
                    conn.rollback()
                pass

    @staticmethod
    def _now_iso() -> str:
        return datetime.utcnow().isoformat()

    # ------------------------------------------------------------------
    # Goals
    # ------------------------------------------------------------------

    def save_goal(self, goal: dict) -> int:
        """Insert a new goal row and return its id."""
        now = self._now_iso()
        params = (
            goal.get("created_at", now),
            goal.get("updated_at", now),
            goal["primary_objective"],
            goal.get("body_comp_goal"),
            goal.get("target_weight_kg"),
            goal.get("weight_change_kg_per_month"),
            goal.get("target_steps_per_day"),
            goal.get("target_sleep_hours"),
            goal.get("target_workouts_per_week"),
            goal.get("target_resting_hr"),
            goal.get("target_vo2max"),
            goal.get("timeline_weeks"),
            goal.get("gym_sessions_per_week"),
            goal.get("runs_per_week"),
            goal.get("run_types"),
            goal.get("gym_description"),
            goal.get("gym_goals"),
            goal.get("running_goals"),
            goal.get("notes"),
            goal.get("is_active", 1),
            goal.get("is_provisional", 0),
        )
        sql = """
            INSERT INTO goals (
                created_at, updated_at, primary_objective,
                body_comp_goal, target_weight_kg, weight_change_kg_per_month,
                target_steps_per_day, target_sleep_hours,
                target_workouts_per_week, target_resting_hr, target_vo2max,
                timeline_weeks, gym_sessions_per_week, runs_per_week,
                run_types, gym_description, gym_goals, running_goals,
                notes, is_active, is_provisional
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        return self._insert_returning_id(sql, params)

    def get_active_goal(self) -> Optional[dict]:
        """Return the most recently inserted active goal, or None."""
        return self._fetchone(
            "SELECT * FROM goals WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
        )

    def deactivate_goal(self, goal_id: int) -> None:
        """Set is_active = 0 for the given goal and update updated_at."""
        self._execute(
            "UPDATE goals SET is_active = 0, updated_at = ? WHERE id = ?",
            (self._now_iso(), goal_id),
        )
        self._commit()

    def confirm_provisional_goal(self, goal_id: int) -> None:
        """Clear the is_provisional flag (set to 0) for the given goal."""
        self._execute(
            "UPDATE goals SET is_provisional = 0, updated_at = ? WHERE id = ?",
            (self._now_iso(), goal_id),
        )
        self._commit()

    # ------------------------------------------------------------------
    # Reviews
    # ------------------------------------------------------------------

    def save_review(self, review: dict) -> int:
        """Insert a new review row and return its id."""
        now = self._now_iso()
        params = (
            review["period"],
            review["start_date"],
            review["end_date"],
            review.get("generated_at", now),
            review.get("report_path"),
            review.get("avg_steps"),
            review.get("avg_sleep_hours"),
            review.get("avg_resting_hr"),
            review.get("avg_hrv"),
            review.get("avg_stress"),
            review.get("avg_body_battery"),
            review.get("avg_spo2"),
            review.get("avg_vo2max"),
            review.get("avg_weight_kg"),
            review.get("avg_body_fat_pct"),
            review.get("workouts_count"),
            review.get("total_volume_kg"),
            review.get("total_run_distance_km"),
        )
        sql = """
            INSERT INTO reviews (
                period, start_date, end_date, generated_at, report_path,
                avg_steps, avg_sleep_hours, avg_resting_hr, avg_hrv, avg_stress,
                avg_body_battery, avg_spo2, avg_vo2max, avg_weight_kg,
                avg_body_fat_pct, workouts_count, total_volume_kg,
                total_run_distance_km
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        return self._insert_returning_id(sql, params)

    def update_review_report_path(self, review_id: int, report_path: str) -> None:
        """Set the report_path for an existing review."""
        self._execute(
            "UPDATE reviews SET report_path = ? WHERE id = ?",
            (report_path, review_id),
        )
        self._commit()

    def get_recent_reviews(self, n: int = 6) -> list[dict]:
        """Return up to *n* most recent reviews, newest first."""
        return self._fetchall(
            "SELECT * FROM reviews ORDER BY id DESC LIMIT ?", (n,)
        )

    # ------------------------------------------------------------------
    # Metrics history
    # ------------------------------------------------------------------

    def save_metrics_history(self, review_id: int, daily_metrics: list[dict]) -> None:
        """Bulk-insert daily metric rows for a given review."""
        sql = self._adapt_sql(
            "INSERT INTO metrics_history (review_id, date, metric_name, metric_value) "
            "VALUES (?, ?, ?, ?)"
        )
        conn = self._get_conn()
        cur = self._cursor()
        for m in daily_metrics:
            cur.execute(sql, (review_id, m["date"], m["metric_name"], m.get("metric_value")))
        conn.commit()

    # ------------------------------------------------------------------
    # Recommendations
    # ------------------------------------------------------------------

    def save_recommendations(self, review_id: int, recommendations: list[dict]) -> None:
        """Bulk-insert recommendation rows linked to *review_id*."""
        now = self._now_iso()
        sql = self._adapt_sql(
            "INSERT INTO recommendations "
            "(review_id, category, priority, text, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)"
        )
        conn = self._get_conn()
        cur = self._cursor()
        for r in recommendations:
            cur.execute(sql, (
                review_id,
                r["category"],
                r.get("priority", 2),
                r["text"],
                r.get("status", "active"),
                now,
            ))
        conn.commit()

    def get_active_recommendations(self) -> list[dict]:
        """Return all recommendations whose status is 'active'."""
        return self._fetchall(
            "SELECT * FROM recommendations WHERE status = 'active' ORDER BY priority ASC, id ASC"
        )

    def update_recommendation_status(
        self, rec_id: int, status: str, note: Optional[str] = None
    ) -> None:
        """Update the status (and optionally add a resolution note) for a recommendation."""
        now = self._now_iso()
        resolved_at = now if status in ("resolved", "escalated", "deprioritized") else None
        self._execute(
            "UPDATE recommendations SET status = ?, resolved_at = ?, resolution_note = ? WHERE id = ?",
            (status, resolved_at, note, rec_id),
        )
        self._commit()

    # ------------------------------------------------------------------
    # Knowledge cache
    # ------------------------------------------------------------------

    def get_cached_knowledge(self, cache_key: str) -> Optional[dict]:
        """Return the cached entry for *cache_key* if it has not expired."""
        entry = self._fetchone(
            "SELECT * FROM knowledge_cache WHERE cache_key = ?", (cache_key,)
        )
        if entry is None:
            return None
        expires_at = datetime.fromisoformat(entry["expires_at"])
        if datetime.utcnow() > expires_at:
            return None
        return entry

    def save_knowledge_cache(
        self, cache_key: str, source: str, query: str, result_text: str
    ) -> None:
        """Insert or replace a knowledge cache entry with a 30-day TTL."""
        now = datetime.utcnow()
        fetched_at = now.isoformat()
        expires_at = (now + timedelta(days=KNOWLEDGE_CACHE_TTL_DAYS)).isoformat()
        self._execute(
            """
            INSERT INTO knowledge_cache (cache_key, source, query, result_text, fetched_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                source = excluded.source,
                query = excluded.query,
                result_text = excluded.result_text,
                fetched_at = excluded.fetched_at,
                expires_at = excluded.expires_at
            """,
            (cache_key, source, query, result_text, fetched_at, expires_at),
        )
        self._commit()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


def get_db() -> DatabaseClient:
    """Return the module-level singleton DatabaseClient.

    Uses PostgreSQL if ``DATABASE_URL`` is set, otherwise SQLite at ``DB_PATH``.
    """
    global _db_singleton
    if _db_singleton is None:
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            _db_singleton = DatabaseClient(database_url=database_url)
        else:
            from config import DB_PATH
            _db_singleton = DatabaseClient(db_path=DB_PATH)
    return _db_singleton
