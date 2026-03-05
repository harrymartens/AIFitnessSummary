"""Unit tests for trend_analyzer.TrendAnalyzer.

Uses the ``tmp_path`` pytest fixture with a real SQLite DB for storage tests.
No mocking of the DB layer — we exercise the real DatabaseClient.
"""

from __future__ import annotations

import sys
import os

# Ensure the project root is on the path regardless of how pytest is invoked.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from db_client import DatabaseClient
from trend_analyzer import TrendAnalyzer


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def make_analyzer(tmp_path) -> TrendAnalyzer:
    """Return a TrendAnalyzer backed by a fresh isolated SQLite DB."""
    db = DatabaseClient(str(tmp_path / "test_trend.db"))
    return TrendAnalyzer(db)


def make_garmin_data(
    avg_daily_steps=8000,
    avg_total_sleep=7.0,
    avg_resting_hr=58.0,
    avg_hrv=52.0,
    avg_stress=35.0,
    avg_charged=80.0,
    avg_spo2=97.5,
    vo2max=48.0,
    avg_weight=85.0,
    avg_body_fat=18.0,
    total_distance_km=15.0,
    daily_steps=None,
) -> dict:
    """Return a garmin_data dict using the spec's expected key layout."""
    return {
        "steps": {
            "avg_daily_steps": avg_daily_steps,
            "daily_steps": daily_steps or [],
        },
        "sleep": {"avg_total_sleep": avg_total_sleep},
        "heart_rate": {"avg_resting_hr": avg_resting_hr},
        "hrv": {"avg_hrv": avg_hrv},
        "stress": {"avg_stress": avg_stress},
        "body_battery": {"avg_charged": avg_charged},
        "spo2": {"avg_spo2": avg_spo2},
        "vo2max": {"vo2max": vo2max},
        "body_composition": {
            "avg_weight": avg_weight,
            "avg_body_fat": avg_body_fat,
        },
        "running": {"total_distance_km": total_distance_km},
    }


def make_hevy_data(
    total_workouts=4,
    total_volume_kg=8000.0,
    volume_by_muscle=None,
) -> dict:
    """Return a hevy_data dict."""
    return {
        "total_workouts": total_workouts,
        "total_volume_kg": total_volume_kg,
        "volume_by_muscle": volume_by_muscle or {},
    }


# ---------------------------------------------------------------------------
# Tests: save_review
# ---------------------------------------------------------------------------


class TestSaveReview:
    """Verify that save_review correctly persists metrics to the database."""

    def test_returns_positive_review_id(self, tmp_path):
        analyzer = make_analyzer(tmp_path)
        review_id = analyzer.save_review(
            period="weekly",
            start_date="2026-01-05",
            end_date="2026-01-11",
            garmin_data=make_garmin_data(),
            hevy_data=make_hevy_data(),
        )
        assert isinstance(review_id, int)
        assert review_id > 0

    def test_metrics_stored_correctly(self, tmp_path):
        analyzer = make_analyzer(tmp_path)
        garmin = make_garmin_data(
            avg_daily_steps=9500,
            avg_total_sleep=7.5,
            avg_resting_hr=56.0,
            avg_hrv=60.0,
            avg_stress=30.0,
            avg_charged=85.0,
            avg_spo2=98.0,
            vo2max=50.0,
            avg_weight=84.5,
            avg_body_fat=17.5,
            total_distance_km=20.0,
        )
        hevy = make_hevy_data(total_workouts=5, total_volume_kg=10000.0)

        review_id = analyzer.save_review(
            period="weekly",
            start_date="2026-01-05",
            end_date="2026-01-11",
            garmin_data=garmin,
            hevy_data=hevy,
            report_path="/tmp/report.md",
        )

        # Retrieve from DB and verify
        reviews = analyzer._db.get_recent_reviews(1)
        assert len(reviews) == 1
        r = reviews[0]

        assert r["id"] == review_id
        assert r["period"] == "weekly"
        assert r["start_date"] == "2026-01-05"
        assert r["end_date"] == "2026-01-11"
        assert r["report_path"] == "/tmp/report.md"
        assert r["avg_steps"] == 9500
        assert r["avg_sleep_hours"] == 7.5
        assert r["avg_resting_hr"] == 56.0
        assert r["avg_hrv"] == 60.0
        assert r["avg_stress"] == 30.0
        assert r["avg_body_battery"] == 85.0
        assert r["avg_spo2"] == 98.0
        assert r["avg_vo2max"] == 50.0
        assert r["avg_weight_kg"] == 84.5
        assert r["avg_body_fat_pct"] == 17.5
        assert r["workouts_count"] == 5
        assert r["total_volume_kg"] == 10000.0
        assert r["total_run_distance_km"] == 20.0

    def test_volume_fallback_to_volume_by_muscle(self, tmp_path):
        """total_volume_kg should be computed from volume_by_muscle if not set."""
        analyzer = make_analyzer(tmp_path)
        hevy = {
            "total_workouts": 3,
            "total_volume_kg": None,
            "volume_by_muscle": {"chest": 2000.0, "back": 3000.0, "legs": 5000.0},
        }
        analyzer.save_review(
            period="weekly",
            start_date="2026-01-05",
            end_date="2026-01-11",
            garmin_data=make_garmin_data(),
            hevy_data=hevy,
        )
        reviews = analyzer._db.get_recent_reviews(1)
        assert reviews[0]["total_volume_kg"] == 10000.0

    def test_none_values_stored_as_null(self, tmp_path):
        """Missing garmin fields should be stored as NULL (None)."""
        analyzer = make_analyzer(tmp_path)
        garmin = {}  # completely empty
        hevy = {}

        analyzer.save_review(
            period="weekly",
            start_date="2026-01-05",
            end_date="2026-01-11",
            garmin_data=garmin,
            hevy_data=hevy,
        )
        reviews = analyzer._db.get_recent_reviews(1)
        r = reviews[0]
        assert r["avg_steps"] is None
        assert r["avg_sleep_hours"] is None
        assert r["workouts_count"] is None
        assert r["total_volume_kg"] is None

    def test_daily_steps_saved_to_metrics_history(self, tmp_path):
        """Daily step data should be persisted to the metrics_history table."""
        analyzer = make_analyzer(tmp_path)
        daily_steps = [
            {"date": "2026-01-05", "steps": 7000},
            {"date": "2026-01-06", "steps": 9500},
            {"date": "2026-01-07", "steps": 8200},
        ]
        garmin = make_garmin_data(daily_steps=daily_steps)
        review_id = analyzer.save_review(
            period="weekly",
            start_date="2026-01-05",
            end_date="2026-01-11",
            garmin_data=garmin,
            hevy_data=make_hevy_data(),
        )

        conn = analyzer._db._get_conn()
        rows = conn.execute(
            "SELECT date, metric_name, metric_value FROM metrics_history WHERE review_id = ? ORDER BY date",
            (review_id,),
        ).fetchall()
        assert len(rows) == 3
        assert rows[0]["date"] == "2026-01-05"
        assert rows[0]["metric_name"] == "steps"
        assert rows[0]["metric_value"] == 7000
        assert rows[1]["metric_value"] == 9500
        assert rows[2]["metric_value"] == 8200

    def test_date_objects_accepted(self, tmp_path):
        """start_date and end_date can be datetime.date objects."""
        import datetime

        analyzer = make_analyzer(tmp_path)
        analyzer.save_review(
            period="weekly",
            start_date=datetime.date(2026, 1, 5),
            end_date=datetime.date(2026, 1, 11),
            garmin_data=make_garmin_data(),
            hevy_data=make_hevy_data(),
        )
        reviews = analyzer._db.get_recent_reviews(1)
        assert reviews[0]["start_date"] == "2026-01-05"
        assert reviews[0]["end_date"] == "2026-01-11"

    def test_increments_review_id(self, tmp_path):
        """Each save_review call should return a distinct, incrementing ID."""
        analyzer = make_analyzer(tmp_path)
        id1 = analyzer.save_review(
            period="weekly",
            start_date="2026-01-05",
            end_date="2026-01-11",
            garmin_data=make_garmin_data(),
            hevy_data=make_hevy_data(),
        )
        id2 = analyzer.save_review(
            period="weekly",
            start_date="2026-01-12",
            end_date="2026-01-18",
            garmin_data=make_garmin_data(),
            hevy_data=make_hevy_data(),
        )
        assert id2 > id1


# ---------------------------------------------------------------------------
# Tests: get_trend_context — edge cases
# ---------------------------------------------------------------------------


class TestGetTrendContextEdgeCases:
    """Verify empty-string behaviour when there are too few reviews."""

    def test_zero_reviews_returns_empty_string(self, tmp_path):
        analyzer = make_analyzer(tmp_path)
        result = analyzer.get_trend_context()
        assert result == ""

    def test_one_review_returns_empty_string(self, tmp_path):
        analyzer = make_analyzer(tmp_path)
        analyzer.save_review(
            period="weekly",
            start_date="2026-01-05",
            end_date="2026-01-11",
            garmin_data=make_garmin_data(),
            hevy_data=make_hevy_data(),
        )
        result = analyzer.get_trend_context()
        assert result == ""


# ---------------------------------------------------------------------------
# Tests: get_trend_context — full formatting with 4 reviews
# ---------------------------------------------------------------------------


class TestGetTrendContextFormatting:
    """Verify table layout and trend labels with multiple reviews."""

    def _save_four_reviews(self, analyzer: TrendAnalyzer):
        """Insert 4 weekly reviews with a clear improving trajectory."""
        reviews = [
            # (start, end, steps, sleep, rhr, hrv, weight, workouts, volume)
            ("2026-01-05", "2026-01-11", 8234, 7.1, 58, 52, 87.2, 4, 8450),
            ("2026-01-12", "2026-01-18", 7891, 6.8, 59, 48, 86.9, 3, 7200),
            ("2026-01-19", "2026-01-25", 9102, 7.4, 57, 55, 86.5, 4, 9100),
            ("2026-01-26", "2026-02-01", 8756, 7.2, 57, 54, 86.1, 5, 10200),
        ]
        for start, end, steps, sleep, rhr, hrv, weight, workouts, volume in reviews:
            analyzer.save_review(
                period="weekly",
                start_date=start,
                end_date=end,
                garmin_data=make_garmin_data(
                    avg_daily_steps=steps,
                    avg_total_sleep=sleep,
                    avg_resting_hr=rhr,
                    avg_hrv=hrv,
                    avg_weight=weight,
                ),
                hevy_data=make_hevy_data(total_workouts=workouts, total_volume_kg=float(volume)),
            )

    def test_returns_non_empty_string(self, tmp_path):
        analyzer = make_analyzer(tmp_path)
        self._save_four_reviews(analyzer)
        result = analyzer.get_trend_context(n=4)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_header_line_present(self, tmp_path):
        analyzer = make_analyzer(tmp_path)
        self._save_four_reviews(analyzer)
        result = analyzer.get_trend_context(n=4)
        assert "[HISTORICAL CONTEXT" in result
        assert "4 REVIEWS" in result

    def test_all_date_ranges_present(self, tmp_path):
        analyzer = make_analyzer(tmp_path)
        self._save_four_reviews(analyzer)
        result = analyzer.get_trend_context(n=4)
        assert "2026-01-05" in result
        assert "2026-01-12" in result
        assert "2026-01-19" in result
        assert "2026-01-26" in result

    def test_trends_section_present(self, tmp_path):
        analyzer = make_analyzer(tmp_path)
        self._save_four_reviews(analyzer)
        result = analyzer.get_trend_context(n=4)
        assert "Trends (oldest→newest):" in result

    def test_steps_trend_label_in_output(self, tmp_path):
        analyzer = make_analyzer(tmp_path)
        self._save_four_reviews(analyzer)
        result = analyzer.get_trend_context(n=4)
        assert "Steps:" in result
        # The label should be one of the known symbols
        assert any(sym in result for sym in ["↑", "↓", "→"])

    def test_sleep_trend_in_output(self, tmp_path):
        analyzer = make_analyzer(tmp_path)
        self._save_four_reviews(analyzer)
        result = analyzer.get_trend_context(n=4)
        assert "Sleep:" in result

    def test_resting_hr_in_output(self, tmp_path):
        analyzer = make_analyzer(tmp_path)
        self._save_four_reviews(analyzer)
        result = analyzer.get_trend_context(n=4)
        assert "Resting HR:" in result

    def test_hrv_in_output(self, tmp_path):
        analyzer = make_analyzer(tmp_path)
        self._save_four_reviews(analyzer)
        result = analyzer.get_trend_context(n=4)
        assert "HRV:" in result

    def test_weight_in_output(self, tmp_path):
        analyzer = make_analyzer(tmp_path)
        self._save_four_reviews(analyzer)
        result = analyzer.get_trend_context(n=4)
        assert "Weight:" in result

    def test_training_volume_in_output(self, tmp_path):
        analyzer = make_analyzer(tmp_path)
        self._save_four_reviews(analyzer)
        result = analyzer.get_trend_context(n=4)
        assert "Training Volume:" in result

    def test_period_label_in_rows(self, tmp_path):
        analyzer = make_analyzer(tmp_path)
        self._save_four_reviews(analyzer)
        result = analyzer.get_trend_context(n=4)
        assert "weekly" in result

    def test_two_reviews_produces_output(self, tmp_path):
        """Exactly 2 reviews is the minimum to generate a context block."""
        analyzer = make_analyzer(tmp_path)
        analyzer.save_review(
            period="weekly",
            start_date="2026-01-05",
            end_date="2026-01-11",
            garmin_data=make_garmin_data(avg_daily_steps=8000),
            hevy_data=make_hevy_data(),
        )
        analyzer.save_review(
            period="weekly",
            start_date="2026-01-12",
            end_date="2026-01-18",
            garmin_data=make_garmin_data(avg_daily_steps=9000),
            hevy_data=make_hevy_data(),
        )
        result = analyzer.get_trend_context()
        assert len(result) > 0
        assert "LAST 2 REVIEWS" in result

    def test_null_fields_render_as_dash(self, tmp_path):
        """Reviews with None metrics should show '—' in the table."""
        analyzer = make_analyzer(tmp_path)
        for _ in range(2):
            analyzer.save_review(
                period="weekly",
                start_date="2026-01-05",
                end_date="2026-01-11",
                garmin_data={},
                hevy_data={},
            )
        result = analyzer.get_trend_context()
        assert "—" in result


# ---------------------------------------------------------------------------
# Tests: _compute_trend_label
# ---------------------------------------------------------------------------


class TestComputeTrendLabel:
    """Unit tests for the trend direction helper."""

    def setup_method(self):
        # We don't need a real DB for these tests
        import tempfile, pathlib

        self._tmp = tempfile.mkdtemp()
        db = DatabaseClient(str(pathlib.Path(self._tmp) / "t.db"))
        self._analyzer = TrendAnalyzer(db)

    # --- Higher is better ---

    def test_improving_higher_is_better(self):
        # Second half average clearly higher than first half
        values = [50.0, 52.0, 60.0, 65.0]
        label = self._analyzer._compute_trend_label(values, higher_is_better=True)
        assert label == "↑ improving"

    def test_declining_higher_is_better(self):
        # Second half average clearly lower than first half
        values = [65.0, 60.0, 52.0, 50.0]
        label = self._analyzer._compute_trend_label(values, higher_is_better=True)
        assert label == "↓ declining"

    def test_stable_higher_is_better(self):
        # Less than 5% change
        values = [100.0, 101.0, 102.0, 101.5]
        label = self._analyzer._compute_trend_label(values, higher_is_better=True)
        assert label == "→ stable"

    # --- Lower is better (e.g. resting HR) ---

    def test_improving_lower_is_better(self):
        # Values decreasing — this is improving when lower is better
        values = [62.0, 61.0, 58.0, 56.0]
        label = self._analyzer._compute_trend_label(values, higher_is_better=False)
        assert label == "↑ improving"

    def test_declining_lower_is_better(self):
        # Values increasing — this is declining when lower is better
        values = [56.0, 58.0, 61.0, 64.0]
        label = self._analyzer._compute_trend_label(values, higher_is_better=False)
        assert label == "↓ declining"

    def test_stable_lower_is_better(self):
        # Less than 5% change
        values = [60.0, 60.5, 61.0, 60.2]
        label = self._analyzer._compute_trend_label(values, higher_is_better=False)
        assert label == "→ stable"

    # --- Edge cases ---

    def test_two_values_improving(self):
        values = [50.0, 60.0]
        label = self._analyzer._compute_trend_label(values, higher_is_better=True)
        assert label == "↑ improving"

    def test_two_values_declining(self):
        values = [60.0, 50.0]
        label = self._analyzer._compute_trend_label(values, higher_is_better=True)
        assert label == "↓ declining"

    def test_single_value_returns_stable(self):
        label = self._analyzer._compute_trend_label([55.0], higher_is_better=True)
        assert label == "→ stable"

    def test_identical_values_returns_stable(self):
        values = [70.0, 70.0, 70.0, 70.0]
        label = self._analyzer._compute_trend_label(values, higher_is_better=True)
        assert label == "→ stable"

    def test_exactly_five_percent_change_is_not_stable(self):
        # 5% change — should NOT be stable (threshold is strictly < 0.05)
        values = [100.0, 100.0, 105.0, 105.0]
        label = self._analyzer._compute_trend_label(values, higher_is_better=True)
        assert label != "→ stable"


# ---------------------------------------------------------------------------
# Tests: _fmt_val
# ---------------------------------------------------------------------------


class TestFmtVal:
    def setup_method(self):
        import tempfile, pathlib

        self._tmp = tempfile.mkdtemp()
        db = DatabaseClient(str(pathlib.Path(self._tmp) / "t.db"))
        self._analyzer = TrendAnalyzer(db)

    def test_none_returns_dash(self):
        assert self._analyzer._fmt_val(None) == "—"

    def test_integer_no_decimals(self):
        assert self._analyzer._fmt_val(8234, decimals=0) == "8234"

    def test_float_with_decimals(self):
        assert self._analyzer._fmt_val(7.123, decimals=1) == "7.1"

    def test_suffix_appended(self):
        assert self._analyzer._fmt_val(86.5, decimals=1, suffix="kg") == "86.5kg"

    def test_zero_value_not_dash(self):
        assert self._analyzer._fmt_val(0, decimals=0) == "0"
