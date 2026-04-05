"""Tests for db_client.DatabaseClient — new schema."""

import sqlite3

import pytest

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db_client import DatabaseClient


def make_db(tmp_path) -> DatabaseClient:
    return DatabaseClient(str(tmp_path / "test_fitness.db"))


class TestSchemaCreation:
    def test_reviews_table_exists(self, tmp_path):
        db = make_db(tmp_path)
        conn = sqlite3.connect(str(tmp_path / "test_fitness.db"))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='reviews'"
        )
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()
        assert "reviews" in tables

    def test_schema_is_idempotent(self, tmp_path):
        make_db(tmp_path)
        make_db(tmp_path)  # should not raise


class TestReviewCRUD:
    def _base_review(self, **overrides) -> dict:
        return {
            "cadence": "weekly",
            "start_date": "2026-01-01",
            "end_date": "2026-01-07",
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
            db.save_review(self._base_review(
                start_date=f"2026-{i+1:02d}-01",
                end_date=f"2026-{i+1:02d}-07",
            ))
        reviews = db.get_recent_reviews(n=3)
        assert len(reviews) == 3

    def test_save_review_preserves_new_fields(self, tmp_path):
        db = make_db(tmp_path)
        review_data = self._base_review(
            cadence="block_checkin",
            block_name="Hypertrophy A",
            block_type="hypertrophy",
            block_week=3,
            programme_week=7,
            avg_sleep_hours=7.2,
            bedtime_consistency_sd=25.0,
            sleep_efficiency_pct=88.5,
            avg_resting_hr=55.0,
            hrv_status="BALANCED",
            avg_weight_kg=82.8,
            avg_protein_g=180.0,
            avg_calories=2900.0,
            total_run_distance_km=18.5,
            easy_run_pct=81.1,
            hard_run_pct=18.9,
        )
        review_id = db.save_review(review_data)
        reviews = db.get_recent_reviews(n=1)
        r = reviews[0]
        assert r["cadence"] == "block_checkin"
        assert r["block_name"] == "Hypertrophy A"
        assert r["block_type"] == "hypertrophy"
        assert r["block_week"] == 3
        assert r["avg_sleep_hours"] == pytest.approx(7.2)
        assert r["hrv_status"] == "BALANCED"
        assert r["easy_run_pct"] == pytest.approx(81.1)

    def test_update_report_path(self, tmp_path):
        db = make_db(tmp_path)
        review_id = db.save_review(self._base_review())
        db.update_review_report_path(review_id, "/tmp/report.md")
        reviews = db.get_recent_reviews(n=1)
        assert reviews[0]["report_path"] == "/tmp/report.md"
