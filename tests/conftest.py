"""Shared pytest fixtures for AIFitnessSummary tests."""
import sys
import os

# Ensure project root is on the path regardless of how pytest is invoked.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from db_client import DatabaseClient


@pytest.fixture
def db(tmp_path):
    """Fresh DatabaseClient backed by a temp SQLite file."""
    return DatabaseClient(str(tmp_path / "test.db"))


@pytest.fixture
def sample_garmin_data():
    """Mock garmin_data dict matching the new garmin_client.collect_all() output."""
    return {
        "sleep": {
            "avg_total_h": 7.2,
            "bedtime_consistency_sd_min": 25,
            "avg_sleep_efficiency_pct": 88.5,
            "nights_tracked": 7,
        },
        "resting_hr": {
            "avg_resting_hr": 55.0,
            "resting_hr_values": [54, 55, 56, 55, 54, 55, 56],
        },
        "sleep_respiration": {"avg_sleep_respiration_brpm": 14.2},
        "hrv": {"hrv_status_label": "BALANCED"},
        "runs": {
            "runs": [],
            "run_count": 2,
            "total_distance_km": 18.5,
            "easy_km": 15.0,
            "hard_km": 3.5,
            "easy_pct": 81.1,
            "hard_pct": 18.9,
        },
        "vo2max": {"vo2_max": 48.5},
        "body_composition": {
            "entries": [],
            "latest_weight_kg": 83.0,
            "avg_weight_kg": 82.8,
        },
        "training_status": {"training_status": "Productive"},
    }


@pytest.fixture
def sample_hevy_data():
    """Mock hevy summary dict matching new hevy_client.summarise_workouts() output."""
    return {
        "workout_count": 4,
        "workout_dates": ["2026-03-30", "2026-03-31", "2026-04-01", "2026-04-03"],
        "sets_per_muscle_group": {
            "Quads": 14,
            "Horizontal Push": 16,
            "Horizontal Pull": 14,
            "Posterior Chain": 12,
            "Vertical Pull": 10,
            "Vertical Push": 8,
            "Isolation": 8,
        },
        "volume_load_per_muscle_group": {
            "Quads": 5600,
            "Horizontal Push": 4800,
        },
        "primary_lift_top_sets": {
            "Bench Press": {"weight_kg": 100, "reps": 5, "estimated_1rm": 116.7},
            "Back Squat": {"weight_kg": 120, "reps": 5, "estimated_1rm": 140.0},
        },
        "exercises": {},
    }


@pytest.fixture
def sample_nutrition_data():
    """Mock nutrition data from nutrition_client."""
    return {
        "weight": {
            "entries": [],
            "latest_weight_kg": 83.0,
            "avg_weight_kg": 82.8,
        },
        "nutrition": {
            "avg_daily_calories": 2900,
            "avg_daily_protein_g": 180,
            "avg_expenditure": 2700,
            "days_logged": 7,
        },
    }
