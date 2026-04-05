"""Tests for hevy_client.py — muscle group taxonomy and workout summarisation."""

import pytest

from hevy_client import classify_muscle_group, epley_1rm


class TestMuscleGroupTaxonomy:
    def test_bench_press(self):
        assert classify_muscle_group("Bench Press", "chest") == "Horizontal Push"

    def test_incline_press(self):
        assert classify_muscle_group("Incline Dumbbell Press", "chest") == "Horizontal Push"

    def test_barbell_row(self):
        assert classify_muscle_group("Barbell Row", "upper_back") == "Horizontal Pull"

    def test_pullup(self):
        assert classify_muscle_group("Pull-Up", "lats") == "Vertical Pull"

    def test_lat_pulldown(self):
        assert classify_muscle_group("Lat Pulldown", "lats") == "Vertical Pull"

    def test_overhead_press(self):
        assert classify_muscle_group("Overhead Press", "shoulders") == "Vertical Push"

    def test_squat(self):
        assert classify_muscle_group("Back Squat", "quadriceps") == "Quads"

    def test_deadlift(self):
        assert classify_muscle_group("Conventional Deadlift", "hamstrings") == "Posterior Chain"

    def test_rdl(self):
        assert classify_muscle_group("Romanian Deadlift", "hamstrings") == "Posterior Chain"

    def test_curl(self):
        assert classify_muscle_group("Barbell Curl", "biceps") == "Isolation"

    def test_lateral_raise(self):
        assert classify_muscle_group("Lateral Raise", "shoulders") == "Isolation"

    def test_unknown_defaults_to_isolation(self):
        assert classify_muscle_group("Weird Exercise", "unknown_muscle") == "Isolation"


class TestEpley1RM:
    def test_single_rep(self):
        assert epley_1rm(100, 1) == 100

    def test_five_reps(self):
        assert epley_1rm(100, 5) == pytest.approx(116.7, abs=0.1)

    def test_ten_reps(self):
        assert epley_1rm(80, 10) == pytest.approx(106.7, abs=0.1)

    def test_zero_weight(self):
        assert epley_1rm(0, 5) == 0.0

    def test_zero_reps(self):
        assert epley_1rm(100, 0) == 0.0
