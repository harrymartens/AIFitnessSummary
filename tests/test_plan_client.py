"""Tests for plan_client.py — training plan parsing and cadence detection."""

import datetime
import tempfile
from pathlib import Path

import pytest

from plan_client import TrainingPlan


SAMPLE_PLAN = """# Training Plan — Test Programme

## Meta
- **Programme:** Test Hypertrophy
- **Goal:** Build muscle
- **Start Date:** 2026-03-16
- **End Date:** 2026-04-26
- **Bodyweight Target Rate:** +0.3 kg/week
- **Protein Target:** 2.0 g/kg bodyweight

## Blocks

### Block 1: Hypertrophy A
- **Type:** hypertrophy
- **Start:** 2026-03-16
- **End:** 2026-04-12
- **Deload Week:** 2026-04-06 to 2026-04-12

### Block 2: Strength
- **Type:** strength
- **Start:** 2026-04-13
- **End:** 2026-04-26
- **Deload Week:** 2026-04-20 to 2026-04-26

## Weekly Schedule
- **Monday:** Upper Body (strength)
- **Tuesday:** Easy Run
- **Wednesday:** Lower Body (strength)
- **Thursday:** Rest
- **Friday:** Upper Body (hypertrophy)
- **Saturday:** Long Run
- **Sunday:** Lower Body (hypertrophy)

## Primary Compound Lifts
- Bench Press
- Back Squat

## Volume Targets (sets/week per muscle group)

### Hypertrophy Blocks
| Muscle Group | Min Sets | Target Sets | Max Sets |
|---|---|---|---|
| Quads | 12 | 16 | 20 |
| Horizontal Push | 12 | 16 | 20 |

### Strength Blocks
| Muscle Group | Min Sets | Target Sets | Max Sets |
|---|---|---|---|
| Quads | 8 | 10 | 14 |
| Horizontal Push | 8 | 10 | 14 |

## Running Targets

### All Blocks
- **Weekly Volume:** 25 km
- **Intensity Distribution:** 80% easy / 20% hard
- **Threshold HR:** 150 bpm
"""


@pytest.fixture
def plan_file(tmp_path):
    p = tmp_path / "plan.md"
    p.write_text(SAMPLE_PLAN)
    return str(p)


@pytest.fixture
def plan(plan_file):
    return TrainingPlan(path=plan_file)


class TestPlanParsing:
    def test_meta(self, plan):
        assert plan.programme_name == "Test Hypertrophy"
        assert plan.goal_statement == "Build muscle"
        assert plan.start_date == datetime.date(2026, 3, 16)
        assert plan.end_date == datetime.date(2026, 4, 26)

    def test_blocks(self, plan):
        assert len(plan.blocks) == 2
        assert plan.blocks[0]["name"] == "Block 1: Hypertrophy A"
        assert plan.blocks[0]["type"] == "hypertrophy"
        assert plan.blocks[1]["type"] == "strength"

    def test_primary_lifts(self, plan):
        assert plan.primary_lifts == ["Bench Press", "Back Squat"]

    def test_weekly_schedule(self, plan):
        assert "Monday" in plan.weekly_schedule
        assert "Rest" in plan.weekly_schedule["Thursday"]

    def test_planned_sessions(self, plan):
        assert plan.get_planned_sessions_per_week() == 4

    def test_planned_runs(self, plan):
        assert plan.get_planned_runs_per_week() == 2

    def test_planned_km(self, plan):
        assert plan.get_planned_weekly_km() == 25.0

    def test_threshold_hr(self, plan):
        assert plan.get_threshold_hr() == 150


class TestBlockDetection:
    def test_current_block(self, plan):
        block = plan.get_current_block(datetime.date(2026, 3, 20))
        assert block["name"] == "Block 1: Hypertrophy A"

    def test_block_week_number(self, plan):
        assert plan.get_block_week_number(datetime.date(2026, 3, 16)) == 1
        assert plan.get_block_week_number(datetime.date(2026, 3, 23)) == 2

    def test_deload_week(self, plan):
        assert plan.is_deload_week(datetime.date(2026, 4, 7)) is True
        assert plan.is_deload_week(datetime.date(2026, 3, 20)) is False

    def test_final_week(self, plan):
        assert plan.is_final_week(datetime.date(2026, 4, 22)) is True
        assert plan.is_final_week(datetime.date(2026, 3, 20)) is False

    def test_outside_plan(self, plan):
        assert plan.get_current_block(datetime.date(2025, 1, 1)) is None


class TestCadenceDetection:
    def test_weekly(self, plan):
        assert plan.get_cadence_type(datetime.date(2026, 3, 20)) == "weekly"

    def test_block_checkin(self, plan):
        assert plan.get_cadence_type(datetime.date(2026, 4, 7)) == "block_checkin"

    def test_end_of_programme(self, plan):
        assert plan.get_cadence_type(datetime.date(2026, 4, 22)) == "end_of_programme"


class TestVolumeTargets:
    def test_hypertrophy_targets(self, plan):
        targets = plan.get_volume_targets("hypertrophy")
        assert "Quads" in targets
        assert targets["Quads"]["min"] == 12
        assert targets["Quads"]["target"] == 16
        assert targets["Quads"]["max"] == 20

    def test_strength_targets(self, plan):
        targets = plan.get_volume_targets("strength")
        assert targets["Quads"]["min"] == 8


class TestPromptContext:
    def test_prompt_contains_plan_info(self, plan):
        ctx = plan.get_plan_context_for_prompt(datetime.date(2026, 3, 20))
        assert "[TRAINING PLAN]" in ctx
        assert "Test Hypertrophy" in ctx
        assert "Hypertrophy A" in ctx
        assert "Bench Press" in ctx
