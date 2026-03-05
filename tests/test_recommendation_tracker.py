"""Unit tests for recommendation_tracker.RecommendationTracker.

Each test that touches persistent storage uses ``tmp_path`` with a real
SQLite DatabaseClient to avoid shared state between tests.
"""

import sys
import os
from datetime import datetime, timezone, timedelta

import pytest

# Ensure the project root is on the path regardless of how pytest is invoked.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db_client import DatabaseClient
from recommendation_tracker import RecommendationTracker


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

SAMPLE_RESPONSE_WITH_RECS = """\
## Executive Summary
Good week overall with solid training consistency.

## Recommendations for Next Period
Keep pushing toward your goals.

---RECOMMENDATIONS---
[HIGH] sleep: Increase sleep duration to at least 7.5 hours per night
[MEDIUM] cardiovascular: Add Zone 2 cardio sessions twice per week
[LOW] nutrition: Consider adding more protein to post-workout meals
---END RECOMMENDATIONS---
"""

SAMPLE_RESPONSE_NO_RECS = """\
## Executive Summary
Good week overall with solid training consistency.

## Recommendations for Next Period
Keep pushing toward your goals, no specific structured items this week.
"""

SAMPLE_RESPONSE_ONLY_LOW = """\
## Executive Summary
Very good week.

---RECOMMENDATIONS---
[LOW] nutrition: Drink more water throughout the day
---END RECOMMENDATIONS---
"""

SAMPLE_RESPONSE_HIGH_MEDIUM_LOW = """\
## Executive Summary
Summary here.

---RECOMMENDATIONS---
[HIGH] sleep: Increase sleep duration to at least 7.5 hours per night
[HIGH] recovery: Reduce training intensity this week to allow recovery
[MEDIUM] cardiovascular: Add Zone 2 cardio sessions twice per week
[LOW] nutrition: Eat more vegetables with each meal
---END RECOMMENDATIONS---
"""


def make_db(tmp_path) -> DatabaseClient:
    """Return a fresh DatabaseClient backed by a file in *tmp_path*."""
    return DatabaseClient(str(tmp_path / "test_fitness.db"))


def make_tracker(tmp_path) -> RecommendationTracker:
    """Return a RecommendationTracker backed by a fresh test DB."""
    return RecommendationTracker(make_db(tmp_path))


def insert_review(db: DatabaseClient) -> int:
    """Insert a minimal review row and return its id."""
    return db.save_review(
        {
            "period": "weekly",
            "start_date": "2026-02-26",
            "end_date": "2026-03-04",
            "generated_at": datetime.utcnow().isoformat(),
        }
    )


# ---------------------------------------------------------------------------
# save_from_response
# ---------------------------------------------------------------------------


class TestSaveFromResponse:
    def test_saves_high_and_medium_only_when_two_or_more_qualify(self, tmp_path):
        """When >= 2 HIGH/MEDIUM recs exist, only those are saved."""
        db = make_db(tmp_path)
        tracker = RecommendationTracker(db)
        review_id = insert_review(db)

        saved = tracker.save_from_response(review_id, SAMPLE_RESPONSE_WITH_RECS)

        # Only HIGH and MEDIUM should be saved (2 recs), not LOW
        assert len(saved) == 2
        priorities = {r["priority"] for r in saved}
        assert priorities <= {1, 2}  # 1=HIGH, 2=MEDIUM
        # LOW (priority=3) must not be present
        assert all(r["priority"] <= 2 for r in saved)

    def test_saved_records_have_ids(self, tmp_path):
        """Returned records must include database-assigned ids."""
        db = make_db(tmp_path)
        tracker = RecommendationTracker(db)
        review_id = insert_review(db)

        saved = tracker.save_from_response(review_id, SAMPLE_RESPONSE_WITH_RECS)

        for rec in saved:
            assert "id" in rec
            assert isinstance(rec["id"], int)
            assert rec["id"] > 0

    def test_returns_empty_list_when_no_recommendations_block(self, tmp_path):
        """If the response contains no ---RECOMMENDATIONS--- block, returns []."""
        db = make_db(tmp_path)
        tracker = RecommendationTracker(db)
        review_id = insert_review(db)

        saved = tracker.save_from_response(review_id, SAMPLE_RESPONSE_NO_RECS)

        assert saved == []

    def test_no_db_writes_when_no_recommendations_block(self, tmp_path):
        """If the response has no block, nothing is written to the DB."""
        db = make_db(tmp_path)
        tracker = RecommendationTracker(db)
        review_id = insert_review(db)

        tracker.save_from_response(review_id, SAMPLE_RESPONSE_NO_RECS)

        assert db.get_active_recommendations() == []

    def test_saves_all_when_fewer_than_two_high_medium(self, tmp_path):
        """When only one (or zero) HIGH/MEDIUM rec exists, all recs are saved."""
        db = make_db(tmp_path)
        tracker = RecommendationTracker(db)
        review_id = insert_review(db)

        saved = tracker.save_from_response(review_id, SAMPLE_RESPONSE_ONLY_LOW)

        # Only 1 rec total; since < 2 qualify for HIGH/MEDIUM filter, save all
        assert len(saved) == 1
        assert saved[0]["priority"] == 3  # LOW

    def test_saved_records_have_correct_category_and_text(self, tmp_path):
        """Saved records carry the category and text from the parsed block."""
        db = make_db(tmp_path)
        tracker = RecommendationTracker(db)
        review_id = insert_review(db)

        saved = tracker.save_from_response(review_id, SAMPLE_RESPONSE_WITH_RECS)

        texts = {r["text"] for r in saved}
        categories = {r["category"] for r in saved}
        assert "Increase sleep duration to at least 7.5 hours per night" in texts
        assert "Add Zone 2 cardio sessions twice per week" in texts
        assert "sleep" in categories
        assert "cardiovascular" in categories

    def test_filters_to_high_medium_when_multiple_qualify(self, tmp_path):
        """With 2 HIGH + 1 MEDIUM + 1 LOW, only the 3 HIGH/MEDIUM are saved."""
        db = make_db(tmp_path)
        tracker = RecommendationTracker(db)
        review_id = insert_review(db)

        saved = tracker.save_from_response(review_id, SAMPLE_RESPONSE_HIGH_MEDIUM_LOW)

        assert len(saved) == 3  # 2 HIGH + 1 MEDIUM
        assert all(r["priority"] <= 2 for r in saved)


# ---------------------------------------------------------------------------
# get_active_for_prompt
# ---------------------------------------------------------------------------


class TestGetActiveForPrompt:
    def test_returns_empty_when_no_active_recs(self, tmp_path):
        """Returns [] when the DB has no active recommendations."""
        tracker = make_tracker(tmp_path)
        assert tracker.get_active_for_prompt() == []

    def test_includes_age_days_field(self, tmp_path):
        """Each returned dict must include an age_days integer field."""
        db = make_db(tmp_path)
        tracker = RecommendationTracker(db)
        review_id = insert_review(db)

        tracker.save_from_response(review_id, SAMPLE_RESPONSE_WITH_RECS)
        recs = tracker.get_active_for_prompt()

        assert len(recs) > 0
        for rec in recs:
            assert "age_days" in rec
            assert isinstance(rec["age_days"], int)
            assert rec["age_days"] >= 0

    def test_sorted_by_priority_asc(self, tmp_path):
        """Results are sorted with lower priority numbers (HIGH) first."""
        db = make_db(tmp_path)
        tracker = RecommendationTracker(db)
        review_id = insert_review(db)

        # Insert LOW first, then HIGH, to verify sort overrides insertion order
        db.save_recommendations(
            review_id,
            [
                {"category": "nutrition", "priority": 3, "text": "Eat more vegetables"},
                {"category": "sleep", "priority": 1, "text": "Sleep more"},
                {"category": "cardiovascular", "priority": 2, "text": "Add cardio"},
            ],
        )

        recs = tracker.get_active_for_prompt()
        priorities = [r["priority"] for r in recs]
        assert priorities == sorted(priorities), "Priorities should be ascending (HIGH first)"

    def test_sorted_by_created_at_desc_within_same_priority(self, tmp_path):
        """Within the same priority tier, newest recommendations come first."""
        db = make_db(tmp_path)
        tracker = RecommendationTracker(db)
        review_id = insert_review(db)

        # Insert two HIGH-priority recs with different timestamps by inserting
        # them with manually-set created_at via direct DB calls
        conn = db._get_conn()
        older_ts = (datetime.utcnow() - timedelta(days=5)).isoformat()
        newer_ts = datetime.utcnow().isoformat()

        conn.execute(
            "INSERT INTO recommendations (review_id, category, priority, text, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (review_id, "sleep", 1, "Older HIGH rec", "active", older_ts),
        )
        conn.execute(
            "INSERT INTO recommendations (review_id, category, priority, text, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (review_id, "recovery", 1, "Newer HIGH rec", "active", newer_ts),
        )
        conn.commit()

        recs = tracker.get_active_for_prompt()
        high_recs = [r for r in recs if r["priority"] == 1]
        assert len(high_recs) == 2
        # Newer should appear first
        assert high_recs[0]["text"] == "Newer HIGH rec"
        assert high_recs[1]["text"] == "Older HIGH rec"

    def test_returned_fields(self, tmp_path):
        """Each returned dict must contain the expected keys."""
        db = make_db(tmp_path)
        tracker = RecommendationTracker(db)
        review_id = insert_review(db)

        db.save_recommendations(
            review_id,
            [{"category": "sleep", "priority": 1, "text": "Sleep more"}],
        )

        recs = tracker.get_active_for_prompt()
        assert len(recs) == 1
        rec = recs[0]
        for key in ("id", "category", "priority", "text", "created_at", "age_days"):
            assert key in rec, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# process_followup
# ---------------------------------------------------------------------------


FOLLOWUP_RESPONSE_RESOLVED = """\
## Recommendations for Next Period

Looking at previous recommendations:

Re: Increase sleep duration to at least 7.5 hours per night → RESOLVED
The user has consistently achieved 7.5+ hours this week.

Re: Add Zone 2 cardio sessions twice per week → CONTINUED
Still working on this, not fully achieved.

---RECOMMENDATIONS---
[HIGH] training: Maintain current training volume
---END RECOMMENDATIONS---
"""

FOLLOWUP_RESPONSE_ESCALATED = """\
## Previous Recommendations Assessment

Re: Increase sleep duration to at least 7.5 hours per night → ESCALATED
Sleep has deteriorated further, now averaging only 5.5 hours. Requires urgent attention.

---RECOMMENDATIONS---
[HIGH] sleep: Urgent: prioritise sleep to avoid health decline
---END RECOMMENDATIONS---
"""

FOLLOWUP_RESPONSE_UNCLEAR = """\
## Recommendations for Next Period

Great work this period. Keep up the good training habits.

---RECOMMENDATIONS---
[MEDIUM] general: Continue current approach
---END RECOMMENDATIONS---
"""


class TestProcessFollowup:
    def _setup_with_recs(self, tmp_path) -> tuple[DatabaseClient, RecommendationTracker, int]:
        db = make_db(tmp_path)
        tracker = RecommendationTracker(db)
        review_id = insert_review(db)
        # Pre-populate active recommendations
        db.save_recommendations(
            review_id,
            [
                {
                    "category": "sleep",
                    "priority": 1,
                    "text": "Increase sleep duration to at least 7.5 hours per night",
                },
                {
                    "category": "cardiovascular",
                    "priority": 2,
                    "text": "Add Zone 2 cardio sessions twice per week",
                },
            ],
        )
        return db, tracker, review_id

    def test_resolved_detection(self, tmp_path):
        """RESOLVED keyword near rec text causes status update to 'resolved'."""
        db, tracker, _ = self._setup_with_recs(tmp_path)

        result = tracker.process_followup(FOLLOWUP_RESPONSE_RESOLVED)

        assert len(result["resolved"]) == 1
        assert result["resolved"][0]["category"] == "sleep"

    def test_resolved_status_persisted_in_db(self, tmp_path):
        """After RESOLVED detection the DB row status is updated."""
        db, tracker, _ = self._setup_with_recs(tmp_path)

        tracker.process_followup(FOLLOWUP_RESPONSE_RESOLVED)

        all_active = db.get_active_recommendations()
        # The sleep rec should no longer be active
        active_categories = {r["category"] for r in all_active}
        assert "sleep" not in active_categories

    def test_escalated_detection(self, tmp_path):
        """ESCALATED keyword near rec text causes status update to 'escalated'."""
        db, tracker, _ = self._setup_with_recs(tmp_path)

        result = tracker.process_followup(FOLLOWUP_RESPONSE_ESCALATED)

        assert len(result["escalated"]) >= 1
        escalated_cats = {r["category"] for r in result["escalated"]}
        assert "sleep" in escalated_cats

    def test_escalated_resolution_note_contains_date(self, tmp_path):
        """Escalated recommendations get a resolution_note with the review date."""
        db, tracker, _ = self._setup_with_recs(tmp_path)
        tracker.process_followup(FOLLOWUP_RESPONSE_ESCALATED)

        conn = db._get_conn()
        rows = conn.execute(
            "SELECT resolution_note FROM recommendations WHERE status = 'escalated'"
        ).fetchall()
        assert len(rows) >= 1
        note = rows[0][0]
        assert note is not None
        assert "Escalated in review" in note

    def test_continued_detection_explicit(self, tmp_path):
        """CONTINUED keyword near rec text leaves the rec active."""
        db, tracker, _ = self._setup_with_recs(tmp_path)

        result = tracker.process_followup(FOLLOWUP_RESPONSE_RESOLVED)

        # The cardio rec should be in continued (CONTINUED keyword present near it)
        continued_texts = {r["text"] for r in result["continued"]}
        assert "Add Zone 2 cardio sessions twice per week" in continued_texts

    def test_fallback_to_continued_when_no_signal(self, tmp_path):
        """If no RESOLVED/ESCALATED/CONTINUED signal is found, rec stays active."""
        db, tracker, _ = self._setup_with_recs(tmp_path)

        result = tracker.process_followup(FOLLOWUP_RESPONSE_UNCLEAR)

        # Both original recs should fall through as continued (no mentions)
        assert len(result["resolved"]) == 0
        assert len(result["escalated"]) == 0
        assert len(result["continued"]) == 2

    def test_returns_summary_dict_structure(self, tmp_path):
        """process_followup always returns a dict with resolved/escalated/continued."""
        tracker = make_tracker(tmp_path)

        result = tracker.process_followup("Some random response text.")

        assert isinstance(result, dict)
        assert "resolved" in result
        assert "escalated" in result
        assert "continued" in result

    def test_empty_db_returns_all_empty_lists(self, tmp_path):
        """With no active recommendations, all lists are empty."""
        tracker = make_tracker(tmp_path)

        result = tracker.process_followup(FOLLOWUP_RESPONSE_RESOLVED)

        assert result == {"resolved": [], "escalated": [], "continued": []}


# ---------------------------------------------------------------------------
# format_followup_summary
# ---------------------------------------------------------------------------


class TestFormatFollowupSummary:
    def _make_rec(self, category: str, priority: int, text: str) -> dict:
        return {
            "id": 1,
            "review_id": 1,
            "category": category,
            "priority": priority,
            "text": text,
            "status": "active",
            "created_at": datetime.utcnow().isoformat(),
            "resolved_at": None,
            "resolution_note": None,
        }

    def test_output_contains_markdown_table_header(self, tmp_path):
        """The output must include the Markdown table header row."""
        tracker = make_tracker(tmp_path)
        result = tracker.format_followup_summary(
            {"resolved": [], "escalated": [], "continued": []}
        )
        # Empty case — should not crash and returns a message
        assert "### Recommendation Follow-up" in result

    def test_resolved_row_shows_checkmark(self, tmp_path):
        """Resolved recommendations include the checkmark emoji indicator."""
        tracker = make_tracker(tmp_path)
        rec = self._make_rec("sleep", 1, "Increase sleep to 7.5 hours")
        result = tracker.format_followup_summary(
            {"resolved": [rec], "escalated": [], "continued": []}
        )
        assert "Resolved" in result
        assert "sleep" in result
        assert "HIGH" in result
        assert "Increase sleep to 7.5 hours" in result

    def test_escalated_row_shows_warning(self, tmp_path):
        """Escalated recommendations include the warning indicator."""
        tracker = make_tracker(tmp_path)
        rec = self._make_rec("recovery", 1, "Reduce training intensity this week")
        result = tracker.format_followup_summary(
            {"resolved": [], "escalated": [rec], "continued": []}
        )
        assert "Escalated" in result
        assert "recovery" in result

    def test_continued_row_shows_arrow(self, tmp_path):
        """Continued recommendations include the arrow indicator."""
        tracker = make_tracker(tmp_path)
        rec = self._make_rec("cardiovascular", 2, "Add Zone 2 cardio 2x/week")
        result = tracker.format_followup_summary(
            {"resolved": [], "escalated": [], "continued": [rec]}
        )
        assert "Continued" in result
        assert "cardiovascular" in result
        assert "MEDIUM" in result

    def test_all_three_categories_in_one_table(self, tmp_path):
        """All three outcome types appear in the same formatted table."""
        tracker = make_tracker(tmp_path)
        resolved_rec = self._make_rec("sleep", 1, "Increase sleep to 7.5h")
        escalated_rec = self._make_rec("recovery", 1, "Reduce training intensity")
        continued_rec = self._make_rec("cardiovascular", 2, "Add Zone 2 cardio 2x/week")

        result = tracker.format_followup_summary(
            {
                "resolved": [resolved_rec],
                "escalated": [escalated_rec],
                "continued": [continued_rec],
            }
        )

        assert "Increase sleep to 7.5h" in result
        assert "Reduce training intensity" in result
        assert "Add Zone 2 cardio 2x/week" in result
        assert "Resolved" in result
        assert "Escalated" in result
        assert "Continued" in result

    def test_long_text_is_truncated(self, tmp_path):
        """Recommendation text longer than 80 characters is truncated."""
        tracker = make_tracker(tmp_path)
        long_text = "A" * 100
        rec = self._make_rec("general", 2, long_text)
        result = tracker.format_followup_summary(
            {"resolved": [rec], "escalated": [], "continued": []}
        )
        # The raw 100-char string should not appear; a truncated version should
        assert long_text not in result
        assert "A" * 80 in result
        assert "..." in result

    def test_no_entries_returns_empty_message(self, tmp_path):
        """When all lists are empty, a human-friendly message is returned."""
        tracker = make_tracker(tmp_path)
        result = tracker.format_followup_summary(
            {"resolved": [], "escalated": [], "continued": []}
        )
        assert "No active recommendations" in result


# ---------------------------------------------------------------------------
# get_recommendation_tracker singleton
# ---------------------------------------------------------------------------


class TestGetRecommendationTrackerSingleton:
    def test_singleton_returns_same_instance(self, monkeypatch, tmp_path):
        """get_recommendation_tracker() returns the same object on repeated calls."""
        import recommendation_tracker as rt_module

        # Reset the module-level singleton before the test
        monkeypatch.setattr(rt_module, "_tracker_singleton", None)

        # Patch get_db to return a fresh test DB so we don't touch the real one
        test_db = make_db(tmp_path)
        monkeypatch.setattr(rt_module, "get_db", lambda: test_db)

        tracker1 = rt_module.get_recommendation_tracker()
        tracker2 = rt_module.get_recommendation_tracker()

        assert tracker1 is tracker2

    def test_singleton_is_recommendation_tracker(self, monkeypatch, tmp_path):
        """get_recommendation_tracker() returns a RecommendationTracker instance."""
        import recommendation_tracker as rt_module

        monkeypatch.setattr(rt_module, "_tracker_singleton", None)
        test_db = make_db(tmp_path)
        monkeypatch.setattr(rt_module, "get_db", lambda: test_db)

        tracker = rt_module.get_recommendation_tracker()

        assert isinstance(tracker, RecommendationTracker)
