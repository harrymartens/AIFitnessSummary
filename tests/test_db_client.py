"""Comprehensive unit tests for db_client.DatabaseClient.

Each test function uses the ``tmp_path`` pytest fixture to get an isolated
temporary directory, ensuring tests never share state through a shared DB file.
"""

import sqlite3
from datetime import datetime, timedelta

import pytest

# ---------------------------------------------------------------------------
# We import DatabaseClient directly (not get_db) so tests can supply their own
# DB path without touching the module-level singleton.
# ---------------------------------------------------------------------------
import sys
import os

# Ensure the project root is on the path regardless of how pytest is invoked.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db_client import DatabaseClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_db(tmp_path) -> DatabaseClient:
    """Return a fresh DatabaseClient backed by a file in *tmp_path*."""
    return DatabaseClient(str(tmp_path / "test_fitness.db"))


# ---------------------------------------------------------------------------
# Schema creation
# ---------------------------------------------------------------------------


class TestSchemaCreation:
    """Verify that all expected tables are created on first use."""

    EXPECTED_TABLES = {
        "goals",
        "reviews",
        "metrics_history",
        "recommendations",
        "knowledge_cache",
    }

    def test_all_tables_exist(self, tmp_path):
        db = make_db(tmp_path)
        conn = sqlite3.connect(str(tmp_path / "test_fitness.db"))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()
        assert self.EXPECTED_TABLES == tables

    def test_schema_is_idempotent(self, tmp_path):
        """Constructing DatabaseClient twice should not raise an error."""
        make_db(tmp_path)
        make_db(tmp_path)  # should not raise


# ---------------------------------------------------------------------------
# Goals
# ---------------------------------------------------------------------------


class TestGoalCRUD:
    def _base_goal(self, **overrides) -> dict:
        return {
            "primary_objective": "weight loss",
            "target_weight_kg": 80.0,
            "target_steps_per_day": 10000,
            **overrides,
        }

    def test_save_goal_returns_int_id(self, tmp_path):
        db = make_db(tmp_path)
        goal_id = db.save_goal(self._base_goal())
        assert isinstance(goal_id, int)
        assert goal_id >= 1

    def test_save_goal_sequential_ids(self, tmp_path):
        db = make_db(tmp_path)
        id1 = db.save_goal(self._base_goal())
        id2 = db.save_goal(self._base_goal(primary_objective="strength building"))
        assert id2 == id1 + 1

    def test_get_active_goal_returns_most_recent(self, tmp_path):
        db = make_db(tmp_path)
        db.save_goal(self._base_goal(primary_objective="general fitness"))
        db.save_goal(self._base_goal(primary_objective="strength building"))
        active = db.get_active_goal()
        assert active is not None
        assert active["primary_objective"] == "strength building"

    def test_get_active_goal_returns_none_when_empty(self, tmp_path):
        db = make_db(tmp_path)
        assert db.get_active_goal() is None

    def test_deactivate_goal_hides_it(self, tmp_path):
        db = make_db(tmp_path)
        goal_id = db.save_goal(self._base_goal())
        db.deactivate_goal(goal_id)
        assert db.get_active_goal() is None

    def test_deactivate_goal_only_affects_target(self, tmp_path):
        db = make_db(tmp_path)
        id1 = db.save_goal(self._base_goal(primary_objective="general fitness"))
        id2 = db.save_goal(self._base_goal(primary_objective="strength building"))
        db.deactivate_goal(id1)
        active = db.get_active_goal()
        assert active is not None
        assert active["id"] == id2

    def test_deactivate_goal_updates_updated_at(self, tmp_path):
        db = make_db(tmp_path)
        goal_id = db.save_goal(self._base_goal())
        conn = sqlite3.connect(str(tmp_path / "test_fitness.db"))
        original_ts = conn.execute(
            "SELECT updated_at FROM goals WHERE id = ?", (goal_id,)
        ).fetchone()[0]
        conn.close()

        db.deactivate_goal(goal_id)

        conn = sqlite3.connect(str(tmp_path / "test_fitness.db"))
        new_ts = conn.execute(
            "SELECT updated_at FROM goals WHERE id = ?", (goal_id,)
        ).fetchone()[0]
        conn.close()
        # updated_at should be >= the original
        assert new_ts >= original_ts

    def test_confirm_provisional_goal(self, tmp_path):
        db = make_db(tmp_path)
        goal_id = db.save_goal(self._base_goal(is_provisional=1))

        active = db.get_active_goal()
        assert active["is_provisional"] == 1

        db.confirm_provisional_goal(goal_id)

        active = db.get_active_goal()
        assert active["is_provisional"] == 0

    def test_goal_defaults_to_active_and_non_provisional(self, tmp_path):
        db = make_db(tmp_path)
        db.save_goal(self._base_goal())
        active = db.get_active_goal()
        assert active["is_active"] == 1
        assert active["is_provisional"] == 0

    def test_goal_optional_fields_default_to_none(self, tmp_path):
        db = make_db(tmp_path)
        db.save_goal({"primary_objective": "general fitness"})
        active = db.get_active_goal()
        for field in (
            "target_weight_kg",
            "target_steps_per_day",
            "target_sleep_hours",
            "target_workouts_per_week",
            "target_resting_hr",
            "target_vo2max",
            "timeline_weeks",
            "notes",
        ):
            assert active[field] is None, f"Expected None for {field}"


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------


class TestReviewCRUD:
    def _base_review(self, **overrides) -> dict:
        return {
            "period": "weekly",
            "start_date": "2026-01-01",
            "end_date": "2026-01-07",
            "avg_steps": 8500.0,
            "workouts_count": 4,
            **overrides,
        }

    def test_save_review_returns_int_id(self, tmp_path):
        db = make_db(tmp_path)
        review_id = db.save_review(self._base_review())
        assert isinstance(review_id, int)
        assert review_id >= 1

    def test_get_recent_reviews_empty(self, tmp_path):
        db = make_db(tmp_path)
        assert db.get_recent_reviews() == []

    def test_get_recent_reviews_newest_first(self, tmp_path):
        db = make_db(tmp_path)
        id1 = db.save_review(self._base_review(start_date="2026-01-01", end_date="2026-01-07"))
        id2 = db.save_review(self._base_review(start_date="2026-01-08", end_date="2026-01-14"))
        id3 = db.save_review(self._base_review(start_date="2026-01-15", end_date="2026-01-21"))

        reviews = db.get_recent_reviews()
        assert [r["id"] for r in reviews] == [id3, id2, id1]

    def test_get_recent_reviews_respects_limit(self, tmp_path):
        db = make_db(tmp_path)
        for i in range(10):
            db.save_review(
                self._base_review(
                    start_date=f"2026-{i+1:02d}-01",
                    end_date=f"2026-{i+1:02d}-07",
                )
            )
        reviews = db.get_recent_reviews(n=3)
        assert len(reviews) == 3

    def test_get_recent_reviews_default_limit_six(self, tmp_path):
        db = make_db(tmp_path)
        for i in range(8):
            db.save_review(
                self._base_review(
                    start_date=f"2026-{i+1:02d}-01",
                    end_date=f"2026-{i+1:02d}-07",
                )
            )
        reviews = db.get_recent_reviews()
        assert len(reviews) == 6

    def test_save_review_preserves_fields(self, tmp_path):
        db = make_db(tmp_path)
        review_data = self._base_review(
            period="monthly",
            avg_sleep_hours=7.2,
            avg_resting_hr=58.0,
            total_run_distance_km=42.5,
        )
        review_id = db.save_review(review_data)
        reviews = db.get_recent_reviews(n=1)
        r = reviews[0]
        assert r["id"] == review_id
        assert r["period"] == "monthly"
        assert r["avg_sleep_hours"] == pytest.approx(7.2)
        assert r["avg_resting_hr"] == pytest.approx(58.0)
        assert r["total_run_distance_km"] == pytest.approx(42.5)


# ---------------------------------------------------------------------------
# Metrics history
# ---------------------------------------------------------------------------


class TestMetricsHistory:
    def test_save_metrics_history_stores_all_rows(self, tmp_path):
        db = make_db(tmp_path)
        review_id = db.save_review(
            {"period": "weekly", "start_date": "2026-01-01", "end_date": "2026-01-07"}
        )
        metrics = [
            {"date": "2026-01-01", "metric_name": "steps", "metric_value": 9000.0},
            {"date": "2026-01-02", "metric_name": "steps", "metric_value": 10500.0},
            {"date": "2026-01-01", "metric_name": "sleep_hours", "metric_value": 7.5},
        ]
        db.save_metrics_history(review_id, metrics)

        conn = sqlite3.connect(str(tmp_path / "test_fitness.db"))
        rows = conn.execute(
            "SELECT * FROM metrics_history WHERE review_id = ?", (review_id,)
        ).fetchall()
        conn.close()
        assert len(rows) == 3

    def test_save_metrics_history_correct_values(self, tmp_path):
        db = make_db(tmp_path)
        review_id = db.save_review(
            {"period": "weekly", "start_date": "2026-01-01", "end_date": "2026-01-07"}
        )
        metrics = [
            {"date": "2026-01-03", "metric_name": "resting_hr", "metric_value": 55.0},
        ]
        db.save_metrics_history(review_id, metrics)

        conn = sqlite3.connect(str(tmp_path / "test_fitness.db"))
        row = conn.execute(
            "SELECT date, metric_name, metric_value FROM metrics_history WHERE review_id = ?",
            (review_id,),
        ).fetchone()
        conn.close()
        assert row[0] == "2026-01-03"
        assert row[1] == "resting_hr"
        assert row[2] == pytest.approx(55.0)

    def test_save_metrics_history_empty_list(self, tmp_path):
        db = make_db(tmp_path)
        review_id = db.save_review(
            {"period": "weekly", "start_date": "2026-01-01", "end_date": "2026-01-07"}
        )
        # Should not raise
        db.save_metrics_history(review_id, [])

        conn = sqlite3.connect(str(tmp_path / "test_fitness.db"))
        count = conn.execute(
            "SELECT COUNT(*) FROM metrics_history WHERE review_id = ?", (review_id,)
        ).fetchone()[0]
        conn.close()
        assert count == 0

    def test_save_metrics_history_none_value_allowed(self, tmp_path):
        db = make_db(tmp_path)
        review_id = db.save_review(
            {"period": "weekly", "start_date": "2026-01-01", "end_date": "2026-01-07"}
        )
        metrics = [{"date": "2026-01-01", "metric_name": "vo2max", "metric_value": None}]
        db.save_metrics_history(review_id, metrics)

        conn = sqlite3.connect(str(tmp_path / "test_fitness.db"))
        row = conn.execute(
            "SELECT metric_value FROM metrics_history WHERE review_id = ?", (review_id,)
        ).fetchone()
        conn.close()
        assert row[0] is None


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------


class TestRecommendations:
    def _base_recs(self) -> list[dict]:
        return [
            {"category": "sleep", "priority": 1, "text": "Go to bed earlier."},
            {"category": "training", "priority": 2, "text": "Add a rest day mid-week."},
            {"category": "nutrition", "priority": 3, "text": "Increase protein intake."},
        ]

    def _make_review(self, db: DatabaseClient) -> int:
        return db.save_review(
            {"period": "weekly", "start_date": "2026-01-01", "end_date": "2026-01-07"}
        )

    def test_save_recommendations_stores_all(self, tmp_path):
        db = make_db(tmp_path)
        review_id = self._make_review(db)
        db.save_recommendations(review_id, self._base_recs())

        conn = sqlite3.connect(str(tmp_path / "test_fitness.db"))
        count = conn.execute(
            "SELECT COUNT(*) FROM recommendations WHERE review_id = ?", (review_id,)
        ).fetchone()[0]
        conn.close()
        assert count == 3

    def test_get_active_recommendations_filters_status(self, tmp_path):
        db = make_db(tmp_path)
        review_id = self._make_review(db)
        db.save_recommendations(review_id, self._base_recs())

        active = db.get_active_recommendations()
        assert len(active) == 3

        # Resolve one
        rec_id = active[0]["id"]
        db.update_recommendation_status(rec_id, "resolved")

        active_after = db.get_active_recommendations()
        assert len(active_after) == 2
        assert all(r["id"] != rec_id for r in active_after)

    def test_get_active_recommendations_ordered_by_priority(self, tmp_path):
        db = make_db(tmp_path)
        review_id = self._make_review(db)
        # Insert in reverse priority order
        recs = [
            {"category": "general", "priority": 3, "text": "Low priority."},
            {"category": "sleep", "priority": 1, "text": "High priority."},
            {"category": "training", "priority": 2, "text": "Medium priority."},
        ]
        db.save_recommendations(review_id, recs)

        active = db.get_active_recommendations()
        priorities = [r["priority"] for r in active]
        assert priorities == sorted(priorities)

    def test_update_recommendation_status_with_note(self, tmp_path):
        db = make_db(tmp_path)
        review_id = self._make_review(db)
        db.save_recommendations(
            review_id, [{"category": "sleep", "priority": 1, "text": "Sleep more."}]
        )
        active = db.get_active_recommendations()
        rec_id = active[0]["id"]

        db.update_recommendation_status(rec_id, "resolved", note="Achieved target sleep.")

        conn = sqlite3.connect(str(tmp_path / "test_fitness.db"))
        row = conn.execute(
            "SELECT status, resolved_at, resolution_note FROM recommendations WHERE id = ?",
            (rec_id,),
        ).fetchone()
        conn.close()
        assert row[0] == "resolved"
        assert row[1] is not None  # resolved_at set
        assert row[2] == "Achieved target sleep."

    def test_update_recommendation_status_escalated_sets_resolved_at(self, tmp_path):
        db = make_db(tmp_path)
        review_id = self._make_review(db)
        db.save_recommendations(
            review_id, [{"category": "cardiovascular", "priority": 1, "text": "See a doctor."}]
        )
        active = db.get_active_recommendations()
        rec_id = active[0]["id"]

        db.update_recommendation_status(rec_id, "escalated")

        conn = sqlite3.connect(str(tmp_path / "test_fitness.db"))
        row = conn.execute(
            "SELECT status, resolved_at FROM recommendations WHERE id = ?", (rec_id,)
        ).fetchone()
        conn.close()
        assert row[0] == "escalated"
        assert row[1] is not None

    def test_get_active_recommendations_empty(self, tmp_path):
        db = make_db(tmp_path)
        assert db.get_active_recommendations() == []

    def test_save_recommendations_defaults_status_to_active(self, tmp_path):
        db = make_db(tmp_path)
        review_id = self._make_review(db)
        db.save_recommendations(
            review_id, [{"category": "general", "priority": 2, "text": "Stay consistent."}]
        )
        active = db.get_active_recommendations()
        assert len(active) == 1
        assert active[0]["status"] == "active"


# ---------------------------------------------------------------------------
# Knowledge cache
# ---------------------------------------------------------------------------


class TestKnowledgeCache:
    def _save(self, db: DatabaseClient, cache_key: str = "key1") -> None:
        db.save_knowledge_cache(
            cache_key=cache_key,
            source="pubmed",
            query="creatine supplementation",
            result_text="Creatine improves strength.",
        )

    def test_get_cached_knowledge_returns_none_for_missing_key(self, tmp_path):
        db = make_db(tmp_path)
        assert db.get_cached_knowledge("nonexistent") is None

    def test_save_and_get_cached_knowledge(self, tmp_path):
        db = make_db(tmp_path)
        self._save(db)
        entry = db.get_cached_knowledge("key1")
        assert entry is not None
        assert entry["cache_key"] == "key1"
        assert entry["source"] == "pubmed"
        assert entry["result_text"] == "Creatine improves strength."

    def test_get_cached_knowledge_returns_none_when_expired(self, tmp_path, monkeypatch):
        """Simulate an already-expired cache entry by manipulating the DB directly."""
        db = make_db(tmp_path)
        self._save(db, cache_key="expired_key")

        # Back-date expires_at to the past
        past = (datetime.utcnow() - timedelta(days=1)).isoformat()
        conn = sqlite3.connect(str(tmp_path / "test_fitness.db"))
        conn.execute(
            "UPDATE knowledge_cache SET expires_at = ? WHERE cache_key = ?",
            (past, "expired_key"),
        )
        conn.commit()
        conn.close()

        # Re-open (same file) — the entry should be treated as expired
        db2 = DatabaseClient(str(tmp_path / "test_fitness.db"))
        assert db2.get_cached_knowledge("expired_key") is None

    def test_save_knowledge_cache_upserts_on_duplicate_key(self, tmp_path):
        """Saving the same cache_key twice should update, not insert a new row."""
        db = make_db(tmp_path)
        self._save(db, cache_key="upsert_key")
        db.save_knowledge_cache(
            cache_key="upsert_key",
            source="examine",
            query="caffeine",
            result_text="Caffeine enhances alertness.",
        )

        conn = sqlite3.connect(str(tmp_path / "test_fitness.db"))
        rows = conn.execute(
            "SELECT * FROM knowledge_cache WHERE cache_key = 'upsert_key'"
        ).fetchall()
        conn.close()
        assert len(rows) == 1  # only one row

        entry = db.get_cached_knowledge("upsert_key")
        assert entry["source"] == "examine"
        assert entry["result_text"] == "Caffeine enhances alertness."

    def test_knowledge_cache_expires_at_is_30_days_from_fetch(self, tmp_path):
        db = make_db(tmp_path)
        before = datetime.utcnow()
        self._save(db, cache_key="ttl_key")
        after = datetime.utcnow()

        conn = sqlite3.connect(str(tmp_path / "test_fitness.db"))
        row = conn.execute(
            "SELECT fetched_at, expires_at FROM knowledge_cache WHERE cache_key = 'ttl_key'"
        ).fetchone()
        conn.close()

        fetched_at = datetime.fromisoformat(row[0])
        expires_at = datetime.fromisoformat(row[1])
        delta = expires_at - fetched_at

        assert 29 <= delta.days <= 30, f"Expected ~30 days TTL, got {delta}"

    def test_unexpired_cache_entry_is_returned(self, tmp_path):
        """An entry with a future expiry should be returned by get_cached_knowledge."""
        db = make_db(tmp_path)
        self._save(db, cache_key="fresh_key")

        entry = db.get_cached_knowledge("fresh_key")
        assert entry is not None
        assert entry["cache_key"] == "fresh_key"

    def test_multiple_cache_keys_are_independent(self, tmp_path):
        db = make_db(tmp_path)
        db.save_knowledge_cache("k1", "pubmed", "sleep", "Sleep is important.")
        db.save_knowledge_cache("k2", "examine", "magnesium", "Magnesium aids sleep.")

        e1 = db.get_cached_knowledge("k1")
        e2 = db.get_cached_knowledge("k2")

        assert e1["source"] == "pubmed"
        assert e2["source"] == "examine"
        assert e1["result_text"] != e2["result_text"]
