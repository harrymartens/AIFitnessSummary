"""
Integration tests for the full review pipeline.
All Garmin, Hevy, Anthropic, and SMTP calls are mocked.
"""
import sys
import os
import datetime

# Ensure project root is on the path regardless of how pytest is invoked.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from db_client import DatabaseClient
from claude_analyzer import ClaudeAnalyzer, _format_data_for_prompt
from report_generator import ReportGenerator
from recommendation_tracker import RecommendationTracker
from trend_analyzer import TrendAnalyzer


# ---------------------------------------------------------------------------
# Helpers — garmin/hevy dicts in the format that report_generator /
# claude_analyzer expect (i.e. collect_all() / summarise_workouts() shape)
# ---------------------------------------------------------------------------

def _garmin_report_data():
    """garmin_data dict in collect_all() format for ReportGenerator / ClaudeAnalyzer."""
    return {
        "stats": {
            "avg_daily_steps": 8432,
            "avg_distance_km": 6.75,
            "avg_active_minutes": 35,
            "avg_intensity_minutes": 28,
            "avg_floors": 4.2,
            "avg_total_calories": 2450,
            "days_with_data": 7,
        },
        "heart_rate": {
            "avg_resting_hr": 58,
            "daily_trend": [
                {"date": "2026-02-25", "resting_hr": 57},
                {"date": "2026-02-26", "resting_hr": 59},
            ],
        },
        "hrv": {
            "period_avg_ms": 52.0,
            "daily": [],
        },
        "sleep": {
            "avg_total_h": 7.2,
            "avg_deep_h": 1.4,
            "avg_rem_h": 1.8,
            "avg_light_h": 4.0,
            "avg_awake_h": 0.3,
            "nightly": [],
        },
        "stress": {"avg_stress": 38.0, "daily": []},
        "body_battery": {"avg_max": 72.0, "avg_min": 45.0, "daily": []},
        "spo2": {"avg_spo2": 96.5, "avg_lowest_spo2": 93.0, "daily": []},
        "respiration": {"avg_waking_brpm": 14.2, "avg_sleep_brpm": 13.5, "daily": []},
        "vo2max": {"vo2_max": 48.5, "fitness_age": 32},
        "training_readiness": {
            "avg_score": 65.0,
            "latest_score": 68,
            "latest_level": "Good",
            "daily": [],
        },
        "training_load": {"avg_load": 120.0, "latest_status": "Optimal", "daily": []},
        "body_composition": {
            "latest_weight_kg": 86.2,
            "avg_weight_kg": 86.4,
            "latest_bmi": 24.1,
            "latest_body_fat_pct": 18.5,
            "entries": [],
        },
        "runs": {
            "run_count": 2,
            "total_distance_km": 14.2,
            "avg_pace_min_km": 5.45,
            "runs": [],
        },
    }


def _hevy_report_data():
    """hevy_summary dict in summarise_workouts() format for ReportGenerator / ClaudeAnalyzer."""
    return {
        "workout_count": 4,
        "workouts_per_week": 4.0,
        "workout_dates": ["2026-02-25", "2026-02-27", "2026-03-01", "2026-03-03"],
        "volume_by_muscle_group": {
            "legs": 3200.0,
            "back": 2800.0,
            "chest": 2100.0,
            "shoulders": 800.0,
            "arms": 340.0,
        },
        "personal_records": [],
        "exercises": {
            "Bench Press": {"muscle_group": "chest", "total_sets": 4, "total_reps": 32, "max_weight_kg": 80.0},
            "Squat": {"muscle_group": "legs", "total_sets": 4, "total_reps": 24, "max_weight_kg": 110.0},
        },
    }


# ===========================================================================
# TestDatabaseIntegration
# ===========================================================================


class TestDatabaseIntegration:
    def test_full_goal_review_cycle(self, db, sample_goal, sample_claude_response):
        """Save a goal, save a review, save recommendations, retrieve them — full round trip."""
        # Save goal
        goal_id = db.save_goal(sample_goal)
        assert isinstance(goal_id, int)

        # Verify goal is active
        active_goal = db.get_active_goal()
        assert active_goal is not None
        assert active_goal["primary_objective"] == "weight loss"

        # Save review
        review_id = db.save_review({
            "period": "weekly",
            "start_date": "2026-02-25",
            "end_date": "2026-03-03",
            "avg_steps": 8432.0,
            "avg_sleep_hours": 7.2,
            "workouts_count": 4,
        })
        assert isinstance(review_id, int)

        # Parse and save recommendations
        recs = ClaudeAnalyzer.parse_recommendations(sample_claude_response)
        assert len(recs) > 0
        db.save_recommendations(review_id, recs)

        # Retrieve active recommendations
        active_recs = db.get_active_recommendations()
        assert len(active_recs) >= 2  # At least HIGH and MEDIUM

        # Verify text is preserved
        texts = [r["text"] for r in active_recs]
        assert any("steps" in t.lower() for t in texts)

    def test_trend_context_after_multiple_reviews(self, db):
        """Save 3 reviews, verify get_trend_context() returns non-empty with all date ranges."""
        analyzer = TrendAnalyzer(db)

        # Build a minimal garmin_data in trend_analyzer format
        def _garmin(steps, sleep_h, rhr):
            return {
                "steps": {"avg_daily_steps": steps, "daily_steps": []},
                "sleep": {"avg_total_sleep": sleep_h},
                "heart_rate": {"avg_resting_hr": rhr},
                "hrv": {"avg_hrv": 50.0},
                "stress": {"avg_stress": 35.0},
                "body_battery": {"avg_charged": 70.0},
                "spo2": {"avg_spo2": 96.0},
                "vo2max": {"vo2max": 48.0},
                "body_composition": {"avg_weight": 86.0, "avg_body_fat": 18.0},
                "running": {"total_distance_km": 10.0},
            }

        hevy = {"total_workouts": 4, "total_volume_kg": 9000.0, "volume_by_muscle": {}}

        analyzer.save_review("weekly", "2026-02-04", "2026-02-10", _garmin(7500, 6.8, 60), hevy)
        analyzer.save_review("weekly", "2026-02-11", "2026-02-17", _garmin(8000, 7.0, 59), hevy)
        analyzer.save_review("weekly", "2026-02-18", "2026-02-24", _garmin(8500, 7.2, 58), hevy)

        trend = analyzer.get_trend_context()

        assert trend  # non-empty
        assert "HISTORICAL CONTEXT" in trend
        # All three date ranges should appear in some form
        assert "2026-02-04" in trend
        assert "2026-02-11" in trend
        assert "2026-02-18" in trend


# ===========================================================================
# TestClaudeAnalyzerIntegration
# ===========================================================================


class TestClaudeAnalyzerIntegration:
    def test_parse_recommendations_from_sample_response(self, sample_claude_response):
        """Verify 3 recs parsed with correct priorities and categories."""
        recs = ClaudeAnalyzer.parse_recommendations(sample_claude_response)

        assert len(recs) == 3

        priorities = [r["priority"] for r in recs]
        assert 1 in priorities  # HIGH
        assert 2 in priorities  # MEDIUM
        assert 3 in priorities  # LOW

        categories = [r["category"] for r in recs]
        assert "cardiovascular" in categories
        assert "sleep" in categories
        assert "training" in categories

    def test_strip_recommendations_block(self, sample_claude_response):
        """Verify the ---RECOMMENDATIONS--- block is removed from the narrative."""
        stripped = ClaudeAnalyzer.strip_recommendations_block(sample_claude_response)

        assert "---RECOMMENDATIONS---" not in stripped
        assert "---END RECOMMENDATIONS---" not in stripped
        # Narrative content should still be present
        assert "Executive Summary" in stripped

    def test_format_data_for_prompt_includes_goal(self, sample_goal):
        """Verify [ACTIVE GOAL] appears in formatted prompt when goal is provided."""
        garmin = _garmin_report_data()
        hevy = _hevy_report_data()

        prompt = _format_data_for_prompt(
            period="weekly",
            start_date="2026-02-25",
            end_date="2026-03-03",
            garmin=garmin,
            hevy=hevy,
            goal=sample_goal,
        )

        assert "[ACTIVE GOAL]" in prompt

    def test_format_data_for_prompt_no_goal(self):
        """Verify no-goal message appears when goal=None."""
        garmin = _garmin_report_data()
        hevy = _hevy_report_data()

        prompt = _format_data_for_prompt(
            period="weekly",
            start_date="2026-02-25",
            end_date="2026-03-03",
            garmin=garmin,
            hevy=hevy,
            goal=None,
        )

        assert "[ACTIVE GOAL]" in prompt
        assert "No active goal" in prompt


# ===========================================================================
# TestReportGeneratorIntegration
# ===========================================================================


class TestReportGeneratorIntegration:
    def test_generate_report_with_all_sections(self, tmp_path, sample_goal, monkeypatch):
        """generate() with full data including goal and trend_context_str — verify headings."""
        # Redirect REPORT_DIR to tmp_path to avoid creating files in project root
        import report_generator as rg_module
        monkeypatch.setattr(rg_module, "REPORT_DIR", tmp_path)
        # Also patch config.REPORT_DIR in the ReportGenerator instance
        import config
        monkeypatch.setattr(config, "REPORT_DIR", tmp_path)

        generator = ReportGenerator()

        # Patch REPORT_DIR on the generator's generate() so it writes to tmp_path
        garmin = _garmin_report_data()
        hevy = _hevy_report_data()

        end_date = datetime.date(2026, 3, 3)
        start_date = datetime.date(2026, 2, 25)

        trend_ctx = (
            "[HISTORICAL CONTEXT — LAST 2 REVIEWS]\n"
            "2026-02-11→02-17    | weekly  | 8,000  | 7.0h   | 59         | 50   | 86.0kg | 4        | 9,000kg\n"
            "2026-02-18→02-24    | weekly  | 8,200  | 7.1h   | 58         | 51   | 86.1kg | 4        | 9,100kg\n"
        )

        output_path = generator.generate(
            period="weekly",
            start_date=start_date,
            end_date=end_date,
            garmin_data=garmin,
            hevy_summary=hevy,
            claude_narrative="## Executive Summary\nGood week.\n## Activity & Cardiovascular Highlights\nSteps on track.",
            goal=sample_goal,
            trend_context_str=trend_ctx,
        )

        content = output_path.read_text()
        assert "Goal Progress" in content
        assert "Progress Over Time" in content

    def test_generate_report_minimal(self, tmp_path, monkeypatch):
        """generate() with minimal data (no goal, no trend) — doesn't crash, has basic headings."""
        import config
        monkeypatch.setattr(config, "REPORT_DIR", tmp_path)

        generator = ReportGenerator()

        garmin = _garmin_report_data()
        hevy = _hevy_report_data()

        output_path = generator.generate(
            period="weekly",
            start_date=datetime.date(2026, 2, 25),
            end_date=datetime.date(2026, 3, 3),
            garmin_data=garmin,
            hevy_summary=hevy,
            claude_narrative="## Executive Summary\nGood week.",
            goal=None,
            trend_context_str=None,
        )

        content = output_path.read_text()
        assert "Weekly Fitness Review" in content
        assert "Activity Overview" in content

    def test_goal_progress_section_on_target(self, tmp_path, monkeypatch):
        """Verify green circle (on target) appears when metric is within 5% of target."""
        import config
        monkeypatch.setattr(config, "REPORT_DIR", tmp_path)

        generator = ReportGenerator()

        garmin = _garmin_report_data()
        # Steps = 9600, target = 10000 → 96% → on target (>= 95%)
        garmin["stats"]["avg_daily_steps"] = 9600

        goal = {
            "primary_objective": "weight loss",
            "target_steps_per_day": 10000,
            "is_provisional": 0,
        }

        output_path = generator.generate(
            period="weekly",
            start_date=datetime.date(2026, 2, 25),
            end_date=datetime.date(2026, 3, 3),
            garmin_data=garmin,
            hevy_summary=_hevy_report_data(),
            claude_narrative="## Executive Summary\nGood week.",
            goal=goal,
        )

        content = output_path.read_text()
        assert "\U0001f7e2" in content  # green circle emoji

    def test_goal_progress_section_off_target(self, tmp_path, monkeypatch):
        """Verify red circle appears when metric is far from target."""
        import config
        monkeypatch.setattr(config, "REPORT_DIR", tmp_path)

        generator = ReportGenerator()

        garmin = _garmin_report_data()
        # Steps = 5000, target = 10000 → 50% → far below target
        garmin["stats"]["avg_daily_steps"] = 5000

        goal = {
            "primary_objective": "weight loss",
            "target_steps_per_day": 10000,
            "is_provisional": 0,
        }

        output_path = generator.generate(
            period="weekly",
            start_date=datetime.date(2026, 2, 25),
            end_date=datetime.date(2026, 3, 3),
            garmin_data=garmin,
            hevy_summary=_hevy_report_data(),
            claude_narrative="## Executive Summary\nPoor week.",
            goal=goal,
        )

        content = output_path.read_text()
        assert "\U0001f534" in content  # red circle emoji


# ===========================================================================
# TestRecommendationTrackerIntegration
# ===========================================================================


class TestRecommendationTrackerIntegration:
    def _make_review(self, db):
        return db.save_review({
            "period": "weekly",
            "start_date": "2026-02-25",
            "end_date": "2026-03-03",
        })

    def test_save_and_retrieve_recommendations(self, db, sample_claude_response):
        """Save from sample_claude_response — verify 2 saved (HIGH+MEDIUM only), retrieve active."""
        tracker = RecommendationTracker(db)
        review_id = self._make_review(db)

        saved = tracker.save_from_response(review_id, sample_claude_response)

        # Only HIGH (priority=1) and MEDIUM (priority=2) should be saved
        assert len(saved) == 2
        priorities = {r["priority"] for r in saved}
        assert priorities == {1, 2}

        # Verify they're retrievable
        active = db.get_active_recommendations()
        assert len(active) == 2
        assert all(r["status"] == "active" for r in active)

    def test_followup_detects_resolved(self, db):
        """Rec with 'Increase daily steps' text — response with RESOLVED → status updated."""
        tracker = RecommendationTracker(db)
        review_id = self._make_review(db)

        rec_text = "Increase daily steps to 10,000 by adding a 20-minute walk"
        db.save_recommendations(review_id, [
            {"category": "cardiovascular", "priority": 1, "text": rec_text},
        ])

        # Simulate Claude's follow-up response mentioning the rec and marking it RESOLVED
        followup_response = (
            f"Regarding the recommendation to {rec_text}: RESOLVED — "
            "User achieved 10,200 steps/day this week."
        )

        result = tracker.process_followup(followup_response)

        assert len(result["resolved"]) == 1
        assert len(result["continued"]) == 0

        # Verify DB status updated
        active = db.get_active_recommendations()
        assert len(active) == 0  # none left active

    def test_followup_unknown_stays_active(self, db):
        """Response with no clear signal — rec stays active (CONTINUED)."""
        tracker = RecommendationTracker(db)
        review_id = self._make_review(db)

        rec_text = "Consider adding a Zone 2 cardio session"
        db.save_recommendations(review_id, [
            {"category": "training", "priority": 3, "text": rec_text},
        ])

        # Response has no RESOLVED/ESCALATED signal near the rec text
        followup_response = (
            "This week was great. Good progress on training goals. "
            "Continued to improve overall fitness."
        )

        result = tracker.process_followup(followup_response)

        # Should stay active (continued)
        assert len(result["continued"]) == 1
        assert len(result["resolved"]) == 0

        # Verify DB unchanged
        active = db.get_active_recommendations()
        assert len(active) == 1
        assert active[0]["status"] == "active"


# ===========================================================================
# TestEmailClientIntegration
# ===========================================================================


class TestEmailClientIntegration:
    def test_send_report_calls_smtp(self, monkeypatch):
        """mock smtplib.SMTP_SSL — verify it's called with correct host/port."""
        monkeypatch.setenv("EMAIL_SENDER", "sender@gmail.com")
        monkeypatch.setenv("EMAIL_RECIPIENT", "recipient@example.com")
        monkeypatch.setenv("GMAIL_APP_PASSWORD", "test_app_password_16")

        from email_client import EmailClient, get_email_client, _SMTP_HOST, _SMTP_PORT

        smtp_calls = []

        class MockSMTPSSL:
            def __init__(self, host, port, context=None):
                smtp_calls.append((host, port))

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def login(self, user, password):
                pass

            def sendmail(self, from_addr, to_addr, msg):
                pass

        import smtplib
        monkeypatch.setattr(smtplib, "SMTP_SSL", MockSMTPSSL)

        client = get_email_client()
        assert client is not None

        result = client.send_report(
            period="weekly",
            end_date="2026-03-03",
            markdown_content="# Test Report\n\nSome content here.",
        )

        assert result is True
        assert len(smtp_calls) == 1
        host_used, port_used = smtp_calls[0]
        assert host_used == _SMTP_HOST
        assert port_used == _SMTP_PORT

    def test_get_email_client_returns_none_without_env(self, monkeypatch):
        """Unset env vars — verify get_email_client() returns None."""
        monkeypatch.delenv("EMAIL_SENDER", raising=False)
        monkeypatch.delenv("EMAIL_RECIPIENT", raising=False)
        monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)

        from email_client import get_email_client

        client = get_email_client()
        assert client is None
