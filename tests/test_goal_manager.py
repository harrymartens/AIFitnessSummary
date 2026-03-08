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
    "primary_objective": "Lean bulk with strength focus",
    "body_comp_goal": "bulk",
    "target_weight_kg": 85.0,
    "weight_change_kg_per_month": 0.5,
    "target_steps_per_day": 10000,
    "target_sleep_hours": 7.5,
    "gym_sessions_per_week": 4,
    "runs_per_week": 3,
    "run_types": "2 easy runs, 1 interval session",
    "gym_description": "4-day upper/lower split",
    "gym_goals": "Bench 100 kg, squat 140 kg",
    "running_goals": "Sub-20 5K",
    "notes": "Focus on strength while maintaining cardio",
    "is_provisional": 0,
}

MINIMAL_GOAL = {
    "primary_objective": "General Fitness",
    "body_comp_goal": None,
    "target_weight_kg": None,
    "weight_change_kg_per_month": None,
    "target_steps_per_day": None,
    "target_sleep_hours": None,
    "gym_sessions_per_week": None,
    "runs_per_week": None,
    "run_types": None,
    "gym_description": None,
    "gym_goals": None,
    "running_goals": None,
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
        assert "Lean bulk" in result
        assert "bulk" in result.lower()
        assert "85.0" in result
        assert "+0.5 kg/month" in result
        assert "10,000" in result
        assert "7.5 hrs/night" in result
        assert "Gym Sessions/Week: 4" in result
        assert "Runs/Week: 3" in result
        assert "2 easy runs" in result
        assert "upper/lower" in result
        assert "Bench 100 kg" in result
        assert "Sub-20 5K" in result
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

    def test_legacy_workouts_field_still_works(self):
        """Old goals with target_workouts_per_week should still display."""
        gm = _make_gm()
        legacy = {"primary_objective": "Get fit", "target_workouts_per_week": 3}
        result = gm.format_goal_for_prompt(legacy)
        assert "Workouts/Week: 3" in result


# ---------------------------------------------------------------------------
# run_wizard tests
# ---------------------------------------------------------------------------

CLAUDE_GOAL_JSON = {
    "primary_objective": "Lean bulk with strength and running focus",
    "body_comp_goal": "bulk",
    "target_weight_kg": 85.0,
    "weight_change_kg_per_month": 0.5,
    "target_steps_per_day": 10000,
    "target_sleep_hours": 8.0,
    "gym_sessions_per_week": 4,
    "runs_per_week": 3,
    "run_types": "2 easy runs, 1 interval session",
    "gym_description": "4-day upper/lower split",
    "gym_goals": "Bench 100 kg",
    "running_goals": "Sub-20 5K",
    "notes": "Lean bulk phase",
}


class TestRunWizard:
    def _wizard_inputs(self, save_answer="y"):
        """Return a list of input() return values for a full wizard run."""
        return [
            "bulk",              # body comp goal
            "85",                # goal weight
            "+0.5",              # weight rate
            "10000",             # daily steps
            "8",                 # sleep hours
            "4",                 # gym sessions
            "3",                 # runs per week
            "2 easy, 1 interval",  # run types
            "upper/lower split", # gym description
            "bench 100kg",       # gym goals
            "sub-20 5k",         # running goals
            "",                  # notes
            save_answer,         # save? (y/n)
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
        assert result["primary_objective"] == "Lean bulk with strength and running focus"
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

    @patch("goal_manager._call_claude")
    def test_wizard_prompt_includes_new_fields(self, mock_call_claude):
        """Verify the prompt sent to Claude includes the new goal fields."""
        mock_call_claude.return_value = json.dumps(CLAUDE_GOAL_JSON)
        mock_db = MagicMock()
        mock_db.save_goal.return_value = 1
        gm = _make_gm(db=mock_db)

        with patch("builtins.input", side_effect=self._wizard_inputs("y")):
            gm.run_wizard()

        prompt = mock_call_claude.call_args[0][0]
        assert "Body comp goal:" in prompt
        assert "Gym sessions per week:" in prompt
        assert "Runs per week:" in prompt
        assert "Run types:" in prompt
        assert "Gym training description:" in prompt
        assert "Gym goals:" in prompt
        assert "Running goals:" in prompt


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
        mock_db.save_goal.assert_called_once()
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
