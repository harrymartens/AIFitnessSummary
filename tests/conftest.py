"""Shared pytest fixtures for AIFitnessSummary tests.

Available to all test modules via pytest's automatic conftest discovery.
"""
import sys
import os

# Ensure project root is on the path regardless of how pytest is invoked.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from pathlib import Path
from db_client import DatabaseClient


@pytest.fixture
def db(tmp_path):
    """Fresh DatabaseClient backed by a temp SQLite file."""
    return DatabaseClient(str(tmp_path / "test.db"))


@pytest.fixture
def sample_garmin_data():
    """Realistic mock garmin_data dict matching garmin_client.collect_all() output."""
    return {
        "steps": {
            "avg_daily_steps": 8432,
            "avg_daily_distance_km": 6.75,
            "total_active_minutes": 245,
            "daily_steps": [
                {"date": "2026-02-25", "steps": 7800},
                {"date": "2026-02-26", "steps": 9100},
                {"date": "2026-02-27", "steps": 8200},
            ]
        },
        "heart_rate": {"avg_resting_hr": 58, "daily_rhr": []},
        "sleep": {
            "avg_total_sleep": 7.2,
            "avg_deep_sleep": 1.4,
            "avg_rem_sleep": 1.8,
            "avg_light_sleep": 4.0,
            "avg_awake": 0.3,
        },
        "hrv": {"avg_hrv": 52.0, "daily_hrv": []},
        "stress": {"avg_stress": 38.0},
        "body_battery": {"avg_charged": 72.0, "avg_drained": 45.0},
        "spo2": {"avg_spo2": 96.5},
        "respiration": {"avg_respiration": 14.2},
        "vo2max": {"vo2max": 48.5},
        "training_readiness": {"avg_readiness": 65.0},
        "training_load": [],
        "body_composition": {
            "avg_weight": 86.2,
            "avg_bmi": 24.1,
            "avg_body_fat": 18.5,
            "muscle_mass_kg": None,
        },
        "running": {
            "run_count": 2,
            "total_distance_km": 14.2,
            "avg_pace_min_per_km": 5.45,
            "avg_hr": 152,
            "runs": [],
        },
        "fitness_age": None,
    }


@pytest.fixture
def sample_hevy_data():
    """Realistic mock hevy_data dict matching hevy_client.summarise_workouts() output."""
    return {
        "total_workouts": 4,
        "workouts_per_week": 4.0,
        "workout_dates": ["2026-02-25", "2026-02-27", "2026-03-01", "2026-03-03"],
        "total_volume_kg": 9240.0,
        "volume_by_muscle": {
            "chest": 2100.0,
            "back": 2800.0,
            "legs": 3200.0,
            "shoulders": 800.0,
            "arms": 340.0,
        },
        "personal_records": [],
        "exercises": [
            {"title": "Bench Press", "muscle_group": "chest", "sets": 4, "reps": 8, "max_weight_kg": 80.0},
            {"title": "Squat", "muscle_group": "legs", "sets": 4, "reps": 6, "max_weight_kg": 110.0},
        ],
        "period_days": 7,
    }


@pytest.fixture
def sample_goal():
    """A realistic active goal dict."""
    return {
        "id": 1,
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
        "target_workouts_per_week": 4,
        "target_resting_hr": 55,
        "target_vo2max": None,
        "timeline_weeks": None,
        "notes": "Focus on strength while maintaining cardio",
        "is_active": 1,
        "is_provisional": 0,
    }


@pytest.fixture
def sample_claude_response():
    """A realistic mock Claude response with recommendations block."""
    return """## Executive Summary
Good week overall with consistent training.

## Activity & Cardiovascular Highlights
Steps averaged 8,432/day, below the 10,000 target.

## Sleep Quality
Sleep averaged 7.2 hours — close to the 7.5 hour goal.

## Recovery & Stress
HRV of 52ms indicates good recovery status.

## Strength Training Analysis
4 workouts completed, meeting the weekly target.

## Training Load Assessment
Training load is appropriate for current fitness level.

## Recommendations for Next Period
Focus on increasing daily step count and sleep consistency.

---RECOMMENDATIONS---
[HIGH] cardiovascular: Increase daily steps to 10,000 by adding a 20-minute walk after dinner — currently averaging 8,432 steps, 16% below target
[MEDIUM] sleep: Aim for 7.5 hours sleep by setting a consistent 10:30pm bedtime — currently averaging 7.2 hours
[LOW] training: Consider adding one additional Zone 2 cardio session per week to improve aerobic base
---END RECOMMENDATIONS---
"""
