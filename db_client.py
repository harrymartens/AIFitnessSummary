"""SQLite database layer for AIFitnessSummary.

Provides the DatabaseClient class for persistent storage of goals, reviews,
metrics history, recommendations, and knowledge cache entries.

Usage:
    from db_client import get_db
    db = get_db()
"""

import sqlite3
from datetime import datetime, timedelta
from typing import Optional

_db_singleton: Optional["DatabaseClient"] = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    primary_objective TEXT NOT NULL,
    target_weight_kg REAL,
    target_steps_per_day INTEGER,
    target_sleep_hours REAL,
    target_workouts_per_week INTEGER,
    target_resting_hr INTEGER,
    target_vo2max REAL,
    timeline_weeks INTEGER,
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

KNOWLEDGE_CACHE_TTL_DAYS = 30


class DatabaseClient:
    """SQLite-backed persistence layer for AIFitnessSummary data."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._init_schema()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        """Return a lazily-created, reused connection with row_factory set."""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
        return self._conn

    def _init_schema(self) -> None:
        """Create all tables if they do not already exist."""
        conn = self._get_conn()
        conn.executescript(SCHEMA_SQL)
        conn.commit()

    @staticmethod
    def _now_iso() -> str:
        return datetime.utcnow().isoformat()

    @staticmethod
    def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict]:
        if row is None:
            return None
        return dict(row)

    # ------------------------------------------------------------------
    # Goals
    # ------------------------------------------------------------------

    def save_goal(self, goal: dict) -> int:
        """Insert a new goal row and return its id.

        The caller may supply any subset of the optional metric columns.
        ``created_at`` and ``updated_at`` are set automatically if absent.
        ``is_active`` defaults to 1; ``is_provisional`` defaults to 0.
        """
        now = self._now_iso()
        row = {
            "created_at": goal.get("created_at", now),
            "updated_at": goal.get("updated_at", now),
            "primary_objective": goal["primary_objective"],
            "target_weight_kg": goal.get("target_weight_kg"),
            "target_steps_per_day": goal.get("target_steps_per_day"),
            "target_sleep_hours": goal.get("target_sleep_hours"),
            "target_workouts_per_week": goal.get("target_workouts_per_week"),
            "target_resting_hr": goal.get("target_resting_hr"),
            "target_vo2max": goal.get("target_vo2max"),
            "timeline_weeks": goal.get("timeline_weeks"),
            "notes": goal.get("notes"),
            "is_active": goal.get("is_active", 1),
            "is_provisional": goal.get("is_provisional", 0),
        }
        conn = self._get_conn()
        cursor = conn.execute(
            """
            INSERT INTO goals (
                created_at, updated_at, primary_objective,
                target_weight_kg, target_steps_per_day, target_sleep_hours,
                target_workouts_per_week, target_resting_hr, target_vo2max,
                timeline_weeks, notes, is_active, is_provisional
            ) VALUES (
                :created_at, :updated_at, :primary_objective,
                :target_weight_kg, :target_steps_per_day, :target_sleep_hours,
                :target_workouts_per_week, :target_resting_hr, :target_vo2max,
                :timeline_weeks, :notes, :is_active, :is_provisional
            )
            """,
            row,
        )
        conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def get_active_goal(self) -> Optional[dict]:
        """Return the most recently inserted active goal, or None."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM goals WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return self._row_to_dict(row)

    def deactivate_goal(self, goal_id: int) -> None:
        """Set is_active = 0 for the given goal and update updated_at."""
        conn = self._get_conn()
        conn.execute(
            "UPDATE goals SET is_active = 0, updated_at = ? WHERE id = ?",
            (self._now_iso(), goal_id),
        )
        conn.commit()

    def confirm_provisional_goal(self, goal_id: int) -> None:
        """Clear the is_provisional flag (set to 0) for the given goal."""
        conn = self._get_conn()
        conn.execute(
            "UPDATE goals SET is_provisional = 0, updated_at = ? WHERE id = ?",
            (self._now_iso(), goal_id),
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Reviews
    # ------------------------------------------------------------------

    def save_review(self, review: dict) -> int:
        """Insert a new review row and return its id."""
        now = self._now_iso()
        row = {
            "period": review["period"],
            "start_date": review["start_date"],
            "end_date": review["end_date"],
            "generated_at": review.get("generated_at", now),
            "report_path": review.get("report_path"),
            "avg_steps": review.get("avg_steps"),
            "avg_sleep_hours": review.get("avg_sleep_hours"),
            "avg_resting_hr": review.get("avg_resting_hr"),
            "avg_hrv": review.get("avg_hrv"),
            "avg_stress": review.get("avg_stress"),
            "avg_body_battery": review.get("avg_body_battery"),
            "avg_spo2": review.get("avg_spo2"),
            "avg_vo2max": review.get("avg_vo2max"),
            "avg_weight_kg": review.get("avg_weight_kg"),
            "avg_body_fat_pct": review.get("avg_body_fat_pct"),
            "workouts_count": review.get("workouts_count"),
            "total_volume_kg": review.get("total_volume_kg"),
            "total_run_distance_km": review.get("total_run_distance_km"),
        }
        conn = self._get_conn()
        cursor = conn.execute(
            """
            INSERT INTO reviews (
                period, start_date, end_date, generated_at, report_path,
                avg_steps, avg_sleep_hours, avg_resting_hr, avg_hrv, avg_stress,
                avg_body_battery, avg_spo2, avg_vo2max, avg_weight_kg,
                avg_body_fat_pct, workouts_count, total_volume_kg,
                total_run_distance_km
            ) VALUES (
                :period, :start_date, :end_date, :generated_at, :report_path,
                :avg_steps, :avg_sleep_hours, :avg_resting_hr, :avg_hrv, :avg_stress,
                :avg_body_battery, :avg_spo2, :avg_vo2max, :avg_weight_kg,
                :avg_body_fat_pct, :workouts_count, :total_volume_kg,
                :total_run_distance_km
            )
            """,
            row,
        )
        conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def get_recent_reviews(self, n: int = 6) -> list[dict]:
        """Return up to *n* most recent reviews, newest first."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM reviews ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Metrics history
    # ------------------------------------------------------------------

    def save_metrics_history(self, review_id: int, daily_metrics: list[dict]) -> None:
        """Bulk-insert daily metric rows for a given review.

        Each element of *daily_metrics* must be a dict with keys:
            ``date``         – "YYYY-MM-DD" string
            ``metric_name``  – e.g. "steps", "sleep_hours"
            ``metric_value`` – numeric value (or None)
        """
        conn = self._get_conn()
        conn.executemany(
            """
            INSERT INTO metrics_history (review_id, date, metric_name, metric_value)
            VALUES (?, ?, ?, ?)
            """,
            [
                (review_id, m["date"], m["metric_name"], m.get("metric_value"))
                for m in daily_metrics
            ],
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Recommendations
    # ------------------------------------------------------------------

    def save_recommendations(self, review_id: int, recommendations: list[dict]) -> None:
        """Bulk-insert recommendation rows linked to *review_id*.

        Each element must have keys: ``category``, ``priority``, ``text``.
        Optional keys: ``status`` (default "active").
        """
        now = self._now_iso()
        conn = self._get_conn()
        conn.executemany(
            """
            INSERT INTO recommendations (
                review_id, category, priority, text, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    review_id,
                    r["category"],
                    r.get("priority", 2),
                    r["text"],
                    r.get("status", "active"),
                    now,
                )
                for r in recommendations
            ],
        )
        conn.commit()

    def get_active_recommendations(self) -> list[dict]:
        """Return all recommendations whose status is 'active'."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM recommendations WHERE status = 'active' ORDER BY priority ASC, id ASC"
        ).fetchall()
        return [dict(r) for r in rows]

    def update_recommendation_status(
        self, rec_id: int, status: str, note: Optional[str] = None
    ) -> None:
        """Update the status (and optionally add a resolution note) for a recommendation."""
        now = self._now_iso()
        resolved_at = now if status in ("resolved", "escalated", "deprioritized") else None
        conn = self._get_conn()
        conn.execute(
            """
            UPDATE recommendations
            SET status = ?, resolved_at = ?, resolution_note = ?
            WHERE id = ?
            """,
            (status, resolved_at, note, rec_id),
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Knowledge cache
    # ------------------------------------------------------------------

    def get_cached_knowledge(self, cache_key: str) -> Optional[dict]:
        """Return the cached entry for *cache_key* if it has not expired.

        Returns None if the key is not found or the entry has expired.
        """
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM knowledge_cache WHERE cache_key = ?", (cache_key,)
        ).fetchone()
        if row is None:
            return None
        entry = dict(row)
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
        conn = self._get_conn()
        conn.execute(
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
        conn.commit()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


def get_db() -> DatabaseClient:
    """Return the module-level singleton DatabaseClient.

    The database path is read from config.DB_PATH (which itself honours the
    ``DB_PATH`` environment variable).
    """
    global _db_singleton
    if _db_singleton is None:
        from config import DB_PATH  # local import avoids circular issues at module load

        _db_singleton = DatabaseClient(DB_PATH)
    return _db_singleton
