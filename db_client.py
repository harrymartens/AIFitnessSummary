"""Database layer for AIFitnessSummary.

Supports two backends selected by environment:
  - **PostgreSQL (Supabase)**: Set ``DATABASE_URL``.
  - **SQLite (local)**: When ``DATABASE_URL`` is not set, falls back to
    a local SQLite file at ``DB_PATH`` (default ``fitness_memory.db``).

Schema aligned with the Health & Performance Digest proposal.
"""

import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

_db_singleton: Optional["DatabaseClient"] = None

SQLITE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cadence TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    report_path TEXT,
    block_name TEXT,
    block_type TEXT,
    block_week INTEGER,
    programme_week INTEGER,
    avg_sleep_hours REAL,
    bedtime_consistency_sd REAL,
    sleep_efficiency_pct REAL,
    avg_resting_hr REAL,
    hrv_status TEXT,
    avg_weight_kg REAL,
    avg_protein_g REAL,
    avg_calories REAL,
    workouts_count INTEGER,
    total_run_distance_km REAL,
    easy_run_pct REAL,
    hard_run_pct REAL
);
"""

PG_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reviews (
    id SERIAL PRIMARY KEY,
    cadence TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    report_path TEXT,
    block_name TEXT,
    block_type TEXT,
    block_week INTEGER,
    programme_week INTEGER,
    avg_sleep_hours DOUBLE PRECISION,
    bedtime_consistency_sd DOUBLE PRECISION,
    sleep_efficiency_pct DOUBLE PRECISION,
    avg_resting_hr DOUBLE PRECISION,
    hrv_status TEXT,
    avg_weight_kg DOUBLE PRECISION,
    avg_protein_g DOUBLE PRECISION,
    avg_calories DOUBLE PRECISION,
    workouts_count INTEGER,
    total_run_distance_km DOUBLE PRECISION,
    easy_run_pct DOUBLE PRECISION,
    hard_run_pct DOUBLE PRECISION
);
"""


class DatabaseClient:
    """Persistence layer for AIFitnessSummary data."""

    def __init__(self, db_path: Optional[str] = None, database_url: Optional[str] = None) -> None:
        self._pg = database_url is not None
        self._conn = None

        if self._pg:
            self._database_url = database_url
        else:
            self.db_path = db_path or "fitness_memory.db"

        self._init_schema()

    def _get_conn(self):
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
        conn = self._get_conn()
        if self._pg:
            import psycopg2.extras
            return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        return conn.cursor()

    def _execute(self, sql: str, params=None):
        cur = self._cursor()
        adapted = self._adapt_sql(sql)
        if params is None:
            cur.execute(adapted)
        else:
            cur.execute(adapted, params)
        return cur

    def _adapt_sql(self, sql: str) -> str:
        if self._pg:
            return sql.replace("?", "%s")
        return sql

    def _fetchone(self, sql: str, params=None) -> Optional[dict]:
        cur = self._execute(sql, params)
        row = cur.fetchone()
        if row is None:
            return None
        return dict(row)

    def _fetchall(self, sql: str, params=None) -> list[dict]:
        cur = self._execute(sql, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]

    def _commit(self):
        self._get_conn().commit()

    def _insert_returning_id(self, sql: str, params) -> int:
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
        conn = self._get_conn()
        if self._pg:
            cur = conn.cursor()
            cur.execute(PG_SCHEMA_SQL)
            conn.commit()
        else:
            conn.executescript(SQLITE_SCHEMA_SQL)
            conn.commit()

    @staticmethod
    def _now_iso() -> str:
        return datetime.utcnow().isoformat()

    # ------------------------------------------------------------------
    # Reviews
    # ------------------------------------------------------------------

    def save_review(self, review: dict) -> int:
        """Insert a new review row and return its id."""
        now = self._now_iso()
        params = (
            review.get("cadence", "weekly"),
            review["start_date"],
            review["end_date"],
            review.get("generated_at", now),
            review.get("report_path"),
            review.get("block_name"),
            review.get("block_type"),
            review.get("block_week"),
            review.get("programme_week"),
            review.get("avg_sleep_hours"),
            review.get("bedtime_consistency_sd"),
            review.get("sleep_efficiency_pct"),
            review.get("avg_resting_hr"),
            review.get("hrv_status"),
            review.get("avg_weight_kg"),
            review.get("avg_protein_g"),
            review.get("avg_calories"),
            review.get("workouts_count"),
            review.get("total_run_distance_km"),
            review.get("easy_run_pct"),
            review.get("hard_run_pct"),
        )
        sql = """
            INSERT INTO reviews (
                cadence, start_date, end_date, generated_at, report_path,
                block_name, block_type, block_week, programme_week,
                avg_sleep_hours, bedtime_consistency_sd, sleep_efficiency_pct,
                avg_resting_hr, hrv_status, avg_weight_kg,
                avg_protein_g, avg_calories,
                workouts_count, total_run_distance_km,
                easy_run_pct, hard_run_pct
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        return self._insert_returning_id(sql, params)

    def update_review_report_path(self, review_id: int, report_path: str) -> None:
        self._execute(
            "UPDATE reviews SET report_path = ? WHERE id = ?",
            (report_path, review_id),
        )
        self._commit()

    def get_recent_reviews(self, n: int = 6) -> list[dict]:
        return self._fetchall(
            "SELECT * FROM reviews ORDER BY id DESC LIMIT ?", (n,)
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

def get_db() -> DatabaseClient:
    """Return the module-level singleton DatabaseClient."""
    global _db_singleton
    if _db_singleton is None:
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            _db_singleton = DatabaseClient(database_url=database_url)
        else:
            from config import DB_PATH
            _db_singleton = DatabaseClient(db_path=DB_PATH)
    return _db_singleton
