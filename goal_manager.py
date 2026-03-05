"""Goal management module for AIFitnessSummary.

Provides GoalManager for interactive goal setup via a CLI wizard,
AI-assisted goal inference from fitness metrics, and goal formatting
for injection into Claude prompts.

Usage:
    from goal_manager import GoalManager
    from db_client import get_db
    from claude_analyzer import ClaudeAnalyzer

    gm = GoalManager(get_db(), ClaudeAnalyzer())
    gm.run_wizard()
"""

import json
import re
from typing import Optional

import anthropic

from config import MODEL

# JSON keys Claude must return
GOAL_KEYS = [
    "primary_objective",
    "target_weight_kg",
    "target_steps_per_day",
    "target_sleep_hours",
    "target_workouts_per_week",
    "target_resting_hr",
    "target_vo2max",
    "timeline_weeks",
    "notes",
]

_CLAUDE_SYSTEM_PROMPT = (
    "You are a fitness goal analyst. Respond only with valid JSON. No explanation, no markdown."
)


def _strip_markdown_fences(text: str) -> str:
    """Remove ```json ... ``` or ``` ... ``` fences from a string."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_goal_json(raw: str) -> Optional[dict]:
    """Try to parse *raw* as JSON. Return dict or None on failure."""
    try:
        cleaned = _strip_markdown_fences(raw)
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return None


def _call_claude(prompt: str) -> str:
    """Make a focused Claude call for JSON extraction and return the text."""
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=512,
        temperature=0,
        system=_CLAUDE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def _display_goal(goal: dict) -> None:
    """Print a human-readable summary of a goal dict."""
    print("\n--- Goal Summary ---")
    print(f"  Primary Objective     : {goal.get('primary_objective', 'N/A')}")
    if goal.get("target_weight_kg") is not None:
        print(f"  Target Weight         : {goal['target_weight_kg']} kg")
    if goal.get("target_steps_per_day") is not None:
        print(f"  Target Steps/Day      : {goal['target_steps_per_day']:,}")
    if goal.get("target_sleep_hours") is not None:
        print(f"  Target Sleep          : {goal['target_sleep_hours']} hrs/night")
    if goal.get("target_workouts_per_week") is not None:
        print(f"  Target Workouts/Week  : {goal['target_workouts_per_week']}")
    if goal.get("target_resting_hr") is not None:
        print(f"  Target Resting HR     : {goal['target_resting_hr']} bpm")
    if goal.get("target_vo2max") is not None:
        print(f"  Target VO2 Max        : {goal['target_vo2max']} ml/kg/min")
    if goal.get("timeline_weeks") is not None:
        print(f"  Timeline              : {goal['timeline_weeks']} weeks")
    if goal.get("notes"):
        print(f"  Notes                 : {goal['notes']}")
    print("--------------------\n")


class GoalManager:
    """Manages fitness goals: wizard setup, inference, retrieval, and formatting."""

    def __init__(self, db, claude) -> None:
        self._db = db
        self._claude = claude  # ClaudeAnalyzer instance (unused directly here but kept for future)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_wizard(self) -> Optional[dict]:
        """Interactive CLI wizard to set up a fitness goal.

        Asks the user a series of questions, passes the answers to Claude
        for structured JSON extraction, displays the parsed goal, and saves
        it to the DB if the user confirms.

        Returns the saved goal dict, or None if the user declines or an
        error occurs.
        """
        print("\n========================================")
        print("  AI Fitness Goal Setup Wizard")
        print("========================================\n")
        print("Let's set up your fitness goal. Answer each question below.")
        print("(Press Enter to skip any optional question.)\n")

        answers = {}

        answers["primary_goal"] = input(
            "What is your primary fitness goal? "
            "(e.g. lose weight, build muscle, improve cardio, general fitness)\n> "
        ).strip()

        answers["current_weight"] = input(
            "\nWhat is your current weight in kg? (press Enter to skip)\n> "
        ).strip()

        answers["target_weight"] = input(
            "\nWhat is your target weight in kg? (press Enter to skip)\n> "
        ).strip()

        answers["timeline_weeks"] = input(
            "\nHow many weeks do you want to achieve this in? (press Enter to skip)\n> "
        ).strip()

        answers["workouts_per_week"] = input(
            "\nHow many workouts per week are you aiming for? (press Enter to skip)\n> "
        ).strip()

        answers["daily_steps"] = input(
            "\nWhat daily step target are you aiming for? (press Enter to skip)\n> "
        ).strip()

        answers["sleep_hours"] = input(
            "\nHow many hours of sleep per night are you aiming for? (press Enter to skip)\n> "
        ).strip()

        answers["notes"] = input(
            "\nAny other notes or context about your goals? (press Enter to skip)\n> "
        ).strip()

        # Build the prompt for Claude
        prompt = self._build_wizard_prompt(answers)

        print("\nAnalysing your goal with AI...\n")
        try:
            raw_response = _call_claude(prompt)
        except Exception as exc:
            print(f"Error calling Claude: {exc}")
            return None

        goal = _parse_goal_json(raw_response)
        if goal is None:
            print("Could not parse AI response as JSON. Raw response:")
            print(raw_response)
            print("\nPlease re-run the wizard: python main.py goals")
            return None

        _display_goal(goal)

        save_answer = input("Save this goal? (y/n)\n> ").strip().lower()
        if save_answer == "y":
            goal["is_provisional"] = 0
            try:
                goal_id = self._db.save_goal(goal)
                print(f"\nGoal saved successfully (id={goal_id}).")
            except Exception as exc:
                print(f"Error saving goal to DB: {exc}")
                return None
            return goal
        else:
            rerun = input("\nWould you like to re-run the wizard? (y/n)\n> ").strip().lower()
            if rerun == "y":
                return self.run_wizard()
            else:
                print("Goal not saved. You can set up your goal anytime with: python main.py goals")
                return None

    def get_active_goal(self) -> Optional[dict]:
        """Return the current active goal from DB, or None."""
        try:
            return self._db.get_active_goal()
        except Exception as exc:
            print(f"Error retrieving active goal: {exc}")
            return None

    def infer_provisional_goal(self, metrics: dict) -> Optional[dict]:
        """Ask Claude to infer a provisional goal from recent metrics.

        Saves the inferred goal with ``is_provisional=1``, displays it to
        the user, and asks for confirmation.  If the user confirms, the
        provisional flag is cleared.  Returns the goal dict in either case,
        or None if the Claude call or DB save fails.
        """
        metrics_summary = self._build_metrics_summary(metrics)

        prompt = (
            "Based on this fitness data, what goal does this person likely have? "
            "Return a JSON goal object with these exact keys: "
            + ", ".join(GOAL_KEYS)
            + ".\n\n"
            + metrics_summary
        )

        print("\nInferring your goal from recent fitness data...")
        try:
            raw_response = _call_claude(prompt)
        except Exception as exc:
            print(f"Error calling Claude: {exc}")
            return None

        goal = _parse_goal_json(raw_response)
        if goal is None:
            print("Could not parse AI response as JSON. Raw response:")
            print(raw_response)
            return None

        goal["is_provisional"] = 1
        try:
            goal_id = self._db.save_goal(goal)
            goal["id"] = goal_id
        except Exception as exc:
            print(f"Error saving provisional goal to DB: {exc}")
            return None

        print("\nNo active goal found. Based on your recent data, I've inferred the following provisional goal:")
        _display_goal(goal)
        print("Would you like to use this as your goal? (y/n)")
        print("You can refine it anytime with: python main.py goals")

        answer = input("> ").strip().lower()
        if answer == "y":
            try:
                self._db.confirm_provisional_goal(goal_id)
                goal["is_provisional"] = 0
                print("\nProvisional goal confirmed as your active goal.")
            except Exception as exc:
                print(f"Error confirming goal: {exc}")
        else:
            print("\nProvisional goal saved but not confirmed. You can set a goal anytime with: python main.py goals")

        return goal

    def format_goal_for_prompt(self, goal: dict) -> str:
        """Format the active goal as a structured text block for Claude prompt injection.

        Example output::

            [ACTIVE GOAL]
            Primary Objective: Weight Loss
            Target Weight: 80 kg (current: 87 kg)
            ...
        """
        lines = ["[ACTIVE GOAL]"]
        lines.append(f"Primary Objective: {goal.get('primary_objective', 'N/A')}")

        if goal.get("target_weight_kg") is not None:
            lines.append(f"Target Weight: {goal['target_weight_kg']} kg")

        if goal.get("target_steps_per_day") is not None:
            lines.append(f"Target Steps/Day: {goal['target_steps_per_day']:,}")

        if goal.get("target_sleep_hours") is not None:
            lines.append(f"Target Sleep: {goal['target_sleep_hours']} hrs/night")

        if goal.get("target_workouts_per_week") is not None:
            lines.append(f"Target Workouts/Week: {goal['target_workouts_per_week']}")

        if goal.get("target_resting_hr") is not None:
            lines.append(f"Target Resting HR: {goal['target_resting_hr']} bpm")

        if goal.get("target_vo2max") is not None:
            lines.append(f"Target VO2 Max: {goal['target_vo2max']} ml/kg/min")

        if goal.get("timeline_weeks") is not None:
            lines.append(f"Timeline: {goal['timeline_weeks']} weeks")

        if goal.get("notes"):
            lines.append(f"Notes: {goal['notes']}")

        is_provisional = goal.get("is_provisional", 0)
        status_label = "Provisional (unconfirmed)" if is_provisional else "Active (confirmed)"
        lines.append(f"Status: {status_label}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_wizard_prompt(answers: dict) -> str:
        """Build the Claude prompt from wizard answers."""
        lines = [
            "A user has described their fitness goal. Interpret what they said and return "
            "a JSON object with these exact keys: "
            + ", ".join(GOAL_KEYS)
            + ".",
            "",
            "Infer reasonable values for any keys the user skipped, based on their stated goal.",
            "Use null for fields that cannot be reasonably inferred.",
            "",
            "User responses:",
            f"  Primary goal: {answers.get('primary_goal') or '(not provided)'}",
            f"  Current weight (kg): {answers.get('current_weight') or '(not provided)'}",
            f"  Target weight (kg): {answers.get('target_weight') or '(not provided)'}",
            f"  Timeline (weeks): {answers.get('timeline_weeks') or '(not provided)'}",
            f"  Workouts per week: {answers.get('workouts_per_week') or '(not provided)'}",
            f"  Daily steps target: {answers.get('daily_steps') or '(not provided)'}",
            f"  Sleep hours target: {answers.get('sleep_hours') or '(not provided)'}",
            f"  Additional notes: {answers.get('notes') or '(none)'}",
        ]
        return "\n".join(lines)

    @staticmethod
    def _build_metrics_summary(metrics: dict) -> str:
        """Build a brief metrics summary string from a metrics dict."""
        lines = ["Recent fitness metrics:"]
        for key, value in metrics.items():
            if value is not None:
                lines.append(f"  {key}: {value}")
        return "\n".join(lines)
