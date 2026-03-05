"""Unit tests for goal_manager.GoalManager."""

import json
from unittest.mock import MagicMock, patch

import pytest

from goal_manager import GoalManager, _strip_markdown_fences, _parse_goal_json


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_gm(db=None, claude=None):
    """Return a GoalManager with mock DB and Claude analyzer."""
    db = db or MagicMock()
    claude = claude or MagicMock()
    return GoalManager(db, claude)


FULL_GOAL = {
    "primary_objective": "Weight Loss",
    "target_weight_kg": 80.0,
    "target_steps_per_day": 10000,
    "target_sleep_hours": 7.5,
    "target_workouts_per_week": 4,
    "target_resting_hr": 60,
    "target_vo2max": 45.0,
    "timeline_weeks": 16,
    "notes": "Focus on fat loss while maintaining muscle mass",
    "is_provisional": 0,
}

MINIMAL_GOAL = {
    "primary_objective": "General Fitness",
    "target_weight_kg": None,
    "target_steps_per_day": None,
    "target_sleep_hours": None,
    "target_workouts_per_week": None,
    "target_resting_hr": None,
    "target_vo2max": None,
    "timeline_weeks": None,
    "notes": None,
    "is_provisional": 0,
}


# ---------------------------------------------------------------------------
# format_goal_for_prompt tests
# ---------------------------------------------------------------------------

class TestFormatGoalForPrompt:
    def test_full_goal_contains_key_fields(self):
        gm = _make_gm()
        result = gm.format_goal_for_prompt(FULL_GOAL)

        assert "[ACTIVE GOAL]" in result
        assert "Weight Loss" in result
        assert "80.0" in result
        assert "10,000" in result
        assert "7.5 hrs/night" in result
        assert "4" in result
        assert "60 bpm" in result
        assert "45.0" in result
        assert "16 weeks" in result
        assert "Focus on fat loss" in result
        assert "Active (confirmed)" in result

    def test_provisional_goal_shows_provisional_status(self):
        gm = _make_gm()
        goal = dict(FULL_GOAL, is_provisional=1)
        result = gm.format_goal_for_prompt(goal)
        assert "Provisional (unconfirmed)" in result

    def test_minimal_goal_no_crash(self):
        """format_goal_for_prompt should not raise even if most fields are None."""
        gm = _make_gm()
        result = gm.format_goal_for_prompt(MINIMAL_GOAL)
        assert "[ACTIVE GOAL]" in result
        assert "General Fitness" in result
        # None fields should simply be absent from output
        assert "None" not in result

    def test_header_always_present(self):
        gm = _make_gm()
        result = gm.format_goal_for_prompt({"primary_objective": "Build Muscle"})
        assert result.startswith("[ACTIVE GOAL]")


# ---------------------------------------------------------------------------
# run_wizard tests
# ---------------------------------------------------------------------------

CLAUDE_GOAL_JSON = {
    "primary_objective": "Weight Loss",
    "target_weight_kg": 80.0,
    "target_steps_per_day": 10000,
    "target_sleep_hours": 7.5,
    "target_workouts_per_week": 4,
    "target_resting_hr": 60,
    "target_vo2max": None,
    "timeline_weeks": 12,
    "notes": "Lose 7 kg over 12 weeks",
}


class TestRunWizard:
    def _wizard_inputs(self, save_answer="y"):
        """Return a list of input() return values for a full wizard run."""
        return [
            "lose weight",   # primary goal
            "87",            # current weight
            "80",            # target weight
            "12",            # timeline weeks
            "4",             # workouts per week
            "10000",         # daily steps
            "7.5",           # sleep hours
            "no sugar",      # notes
            save_answer,     # save? (y/n)
        ]

    @patch("goal_manager._call_claude")
    def test_wizard_saves_goal_when_user_confirms(self, mock_call_claude):
        mock_call_claude.return_value = json.dumps(CLAUDE_GOAL_JSON)
        mock_db = MagicMock()
        mock_db.save_goal.return_value = 1
        gm = _make_gm(db=mock_db)

        with patch("builtins.input", side_effect=self._wizard_inputs("y")):
            result = gm.run_wizard()

        assert result is not None
        assert result["primary_objective"] == "Weight Loss"
        assert result["is_provisional"] == 0
        mock_db.save_goal.assert_called_once()
        saved_arg = mock_db.save_goal.call_args[0][0]
        assert saved_arg["is_provisional"] == 0

    @patch("goal_manager._call_claude")
    def test_wizard_does_not_save_when_user_declines_then_exits(self, mock_call_claude):
        mock_call_claude.return_value = json.dumps(CLAUDE_GOAL_JSON)
        mock_db = MagicMock()
        gm = _make_gm(db=mock_db)

        # User says 'n' to save, then 'n' to re-run
        inputs = self._wizard_inputs("n") + ["n"]
        with patch("builtins.input", side_effect=inputs):
            result = gm.run_wizard()

        assert result is None
        mock_db.save_goal.assert_not_called()

    @patch("goal_manager._call_claude")
    def test_wizard_handles_markdown_fenced_json(self, mock_call_claude):
        fenced = "```json\n" + json.dumps(CLAUDE_GOAL_JSON) + "\n```"
        mock_call_claude.return_value = fenced
        mock_db = MagicMock()
        mock_db.save_goal.return_value = 42
        gm = _make_gm(db=mock_db)

        with patch("builtins.input", side_effect=self._wizard_inputs("y")):
            result = gm.run_wizard()

        assert result is not None
        mock_db.save_goal.assert_called_once()

    @patch("goal_manager._call_claude")
    def test_wizard_returns_none_on_invalid_json(self, mock_call_claude):
        """Invalid JSON from Claude should not crash; wizard returns None."""
        mock_call_claude.return_value = "This is not JSON at all."
        mock_db = MagicMock()
        gm = _make_gm(db=mock_db)

        with patch("builtins.input", side_effect=self._wizard_inputs("y")):
            result = gm.run_wizard()

        assert result is None
        mock_db.save_goal.assert_not_called()

    @patch("goal_manager._call_claude")
    def test_wizard_returns_none_on_claude_exception(self, mock_call_claude):
        """Exception from Claude call should not crash wizard; returns None."""
        mock_call_claude.side_effect = RuntimeError("API error")
        mock_db = MagicMock()
        gm = _make_gm(db=mock_db)

        with patch("builtins.input", side_effect=self._wizard_inputs("y")):
            result = gm.run_wizard()

        assert result is None
        mock_db.save_goal.assert_not_called()


# ---------------------------------------------------------------------------
# infer_provisional_goal tests
# ---------------------------------------------------------------------------

SAMPLE_METRICS = {
    "avg_steps": 6500,
    "avg_sleep_hours": 6.2,
    "avg_weight_kg": 87.0,
    "avg_resting_hr": 72,
    "workouts_count": 2,
}


class TestInferProvisionalGoal:
    @patch("goal_manager._call_claude")
    def test_saves_as_provisional_and_confirms_when_user_accepts(self, mock_call_claude):
        mock_call_claude.return_value = json.dumps(CLAUDE_GOAL_JSON)
        mock_db = MagicMock()
        mock_db.save_goal.return_value = 7
        gm = _make_gm(db=mock_db)

        with patch("builtins.input", return_value="y"):
            result = gm.infer_provisional_goal(SAMPLE_METRICS)

        assert result is not None
        # Initially saved as provisional
        saved_arg = mock_db.save_goal.call_args[0][0]
        assert saved_arg["is_provisional"] == 1
        # Then confirmed
        mock_db.confirm_provisional_goal.assert_called_once_with(7)
        assert result["is_provisional"] == 0

    @patch("goal_manager._call_claude")
    def test_stays_provisional_when_user_declines(self, mock_call_claude):
        mock_call_claude.return_value = json.dumps(CLAUDE_GOAL_JSON)
        mock_db = MagicMock()
        mock_db.save_goal.return_value = 8
        gm = _make_gm(db=mock_db)

        with patch("builtins.input", return_value="n"):
            result = gm.infer_provisional_goal(SAMPLE_METRICS)

        assert result is not None
        assert result["is_provisional"] == 1
        mock_db.confirm_provisional_goal.assert_not_called()

    @patch("goal_manager._call_claude")
    def test_returns_none_on_invalid_json(self, mock_call_claude):
        mock_call_claude.return_value = "not json"
        mock_db = MagicMock()
        gm = _make_gm(db=mock_db)

        result = gm.infer_provisional_goal(SAMPLE_METRICS)

        assert result is None
        mock_db.save_goal.assert_not_called()

    @patch("goal_manager._call_claude")
    def test_returns_none_on_db_failure(self, mock_call_claude):
        mock_call_claude.return_value = json.dumps(CLAUDE_GOAL_JSON)
        mock_db = MagicMock()
        mock_db.save_goal.side_effect = Exception("DB error")
        gm = _make_gm(db=mock_db)

        result = gm.infer_provisional_goal(SAMPLE_METRICS)

        assert result is None


# ---------------------------------------------------------------------------
# get_active_goal tests
# ---------------------------------------------------------------------------

class TestGetActiveGoal:
    def test_returns_goal_from_db(self):
        mock_db = MagicMock()
        mock_db.get_active_goal.return_value = FULL_GOAL
        gm = _make_gm(db=mock_db)
        result = gm.get_active_goal()
        assert result == FULL_GOAL

    def test_returns_none_when_db_raises(self):
        mock_db = MagicMock()
        mock_db.get_active_goal.side_effect = Exception("connection failed")
        gm = _make_gm(db=mock_db)
        result = gm.get_active_goal()
        assert result is None


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

class TestStripMarkdownFences:
    def test_strips_json_fence(self):
        raw = "```json\n{\"key\": \"value\"}\n```"
        assert _strip_markdown_fences(raw) == '{"key": "value"}'

    def test_strips_plain_fence(self):
        raw = "```\n{\"key\": \"value\"}\n```"
        assert _strip_markdown_fences(raw) == '{"key": "value"}'

    def test_no_fence_unchanged(self):
        raw = '{"key": "value"}'
        assert _strip_markdown_fences(raw) == raw


class TestParseGoalJson:
    def test_valid_json(self):
        raw = json.dumps({"primary_objective": "Lose Weight"})
        result = _parse_goal_json(raw)
        assert result == {"primary_objective": "Lose Weight"}

    def test_fenced_json(self):
        raw = "```json\n" + json.dumps({"primary_objective": "Build Muscle"}) + "\n```"
        result = _parse_goal_json(raw)
        assert result["primary_objective"] == "Build Muscle"

    def test_invalid_json_returns_none(self):
        result = _parse_goal_json("this is not json")
        assert result is None

    def test_empty_string_returns_none(self):
        result = _parse_goal_json("")
        assert result is None
