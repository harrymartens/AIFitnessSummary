"""Tests for aggregator.py — data aggregation and escalation flags."""

import pytest

from aggregator import aggregate_weekly, detect_escalation_flags


def _sample_garmin():
    return {
        "sleep": {
            "avg_total_h": 7.2,
            "bedtime_consistency_sd_min": 30,
            "avg_sleep_efficiency_pct": 88.5,
            "nights_tracked": 7,
        },
        "resting_hr": {"avg_resting_hr": 55.0, "resting_hr_values": [54, 55, 56, 55, 54, 55, 56]},
        "sleep_respiration": {"avg_sleep_respiration_brpm": 14.2},
        "hrv": {"hrv_status_label": "BALANCED"},
        "runs": {
            "runs": [], "run_count": 2, "total_distance_km": 18.5,
            "easy_km": 15.0, "hard_km": 3.5, "easy_pct": 81.1, "hard_pct": 18.9,
        },
        "vo2max": {"vo2_max": 48.5},
        "body_composition": {"entries": [], "latest_weight_kg": 83.0, "avg_weight_kg": 82.8},
        "training_status": {"training_status": "Productive"},
    }


def _sample_hevy():
    return {
        "workout_count": 4,
        "workout_dates": ["2026-03-30", "2026-03-31", "2026-04-01", "2026-04-03"],
        "sets_per_muscle_group": {"Quads": 14, "Horizontal Push": 16, "Isolation": 10},
        "volume_load_per_muscle_group": {"Quads": 5600, "Horizontal Push": 4800},
        "primary_lift_top_sets": {
            "Bench Press": {"weight_kg": 100, "reps": 5, "estimated_1rm": 116.7},
        },
        "exercises": {},
    }


def _sample_nutrition():
    return {
        "weight": {"entries": [], "latest_weight_kg": 83.0, "avg_weight_kg": 82.8},
        "nutrition": {"avg_daily_calories": 2900, "avg_daily_protein_g": 180, "avg_expenditure": 2700, "days_logged": 7},
    }


class TestWeeklyAggregation:
    def test_all_domains_present(self):
        summary = aggregate_weekly(_sample_garmin(), _sample_hevy(), _sample_nutrition())
        assert summary["sleep_avg_duration_h"] == 7.2
        assert summary["resting_hr_avg_bpm"] == 55.0
        assert summary["hrv_status_label"] == "BALANCED"
        assert summary["strength_sessions_completed"] == 4
        assert summary["running_total_km"] == 18.5
        assert summary["nutrition_avg_protein_g"] == 180
        assert summary["bodyweight_avg_kg"] == 82.8

    def test_with_plan_targets(self):
        plan = {
            "volume_targets": {"Quads": {"min": 12, "target": 16, "max": 20}},
            "planned_weekly_km": 25.0,
            "planned_sessions": 4,
            "planned_runs": 2,
        }
        summary = aggregate_weekly(_sample_garmin(), _sample_hevy(), _sample_nutrition(), plan)
        assert summary["running_planned_km"] == 25.0
        assert summary["strength_sessions_planned"] == 4
        assert summary["running_volume_compliance_pct"] == 74.0

    def test_empty_data(self):
        summary = aggregate_weekly({}, {}, None)
        assert summary["sleep_avg_duration_h"] is None
        assert summary["strength_sessions_completed"] == 0


class TestEscalationFlags:
    def test_no_flags_when_healthy(self):
        summary = aggregate_weekly(_sample_garmin(), _sample_hevy(), _sample_nutrition())
        flags = detect_escalation_flags(summary)
        assert len(flags) == 0

    def test_bedtime_consistency_flag(self):
        garmin = _sample_garmin()
        garmin["sleep"]["bedtime_consistency_sd_min"] = 60
        summary = aggregate_weekly(garmin, _sample_hevy(), _sample_nutrition())
        flags = detect_escalation_flags(summary)
        conditions = [f["condition"] for f in flags]
        assert any("Bedtime consistency" in c for c in conditions)

    def test_under_stimulation_flag(self):
        hevy = _sample_hevy()
        hevy["sets_per_muscle_group"]["Quads"] = 6
        summary = aggregate_weekly(_sample_garmin(), hevy, _sample_nutrition())
        flags = detect_escalation_flags(summary)
        conditions = [f["condition"] for f in flags]
        assert any("Quads" in c and "<10" in c for c in conditions)

    def test_over_volume_flag(self):
        hevy = _sample_hevy()
        hevy["sets_per_muscle_group"]["Quads"] = 24
        summary = aggregate_weekly(_sample_garmin(), hevy, _sample_nutrition())
        flags = detect_escalation_flags(summary)
        conditions = [f["condition"] for f in flags]
        assert any("Quads" in c and ">20" in c for c in conditions)

    def test_hard_running_flag(self):
        garmin = _sample_garmin()
        garmin["runs"]["hard_pct"] = 35.0
        summary = aggregate_weekly(garmin, _sample_hevy(), _sample_nutrition())
        flags = detect_escalation_flags(summary)
        conditions = [f["condition"] for f in flags]
        assert any("Hard running" in c for c in conditions)

    def test_protein_flag(self):
        nutrition = _sample_nutrition()
        nutrition["nutrition"]["avg_daily_protein_g"] = 100
        summary = aggregate_weekly(_sample_garmin(), _sample_hevy(), nutrition)
        flags = detect_escalation_flags(summary, bodyweight_kg=83.0)
        conditions = [f["condition"] for f in flags]
        assert any("Protein" in c for c in conditions)
