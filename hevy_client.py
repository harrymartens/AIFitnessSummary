"""Hevy App REST API client for AIFitnessSummary.

Tracks strength training metrics per proposal Section 4.2:
- Sets per muscle group vs target range
- Week-over-week volume change per muscle group
- Top set load on primary compound lifts
- Session adherence (completed vs planned)
- Estimated 1RM on primary lifts (block check-in only, Epley formula)

Muscle group taxonomy (7 groups mapped from Hevy exercise tags):
- Quads, Posterior Chain, Horizontal Push, Horizontal Pull,
  Vertical Pull, Vertical Push, Isolation
"""

import datetime
import os

import requests

from config import DATE_FORMAT

HEVY_BASE_URL = "https://api.hevyapp.com"
PAGE_SIZE = 10  # Hevy API maximum

# ---------------------------------------------------------------------------
# Muscle group taxonomy mapping
# Maps Hevy's primary_muscle_group tags to the 7-group taxonomy
# ---------------------------------------------------------------------------

MUSCLE_GROUP_MAP = {
    # Quads
    "quadriceps": "Quads",
    "quads": "Quads",
    # Posterior Chain
    "hamstrings": "Posterior Chain",
    "glutes": "Posterior Chain",
    "lower_back": "Posterior Chain",
    "lower back": "Posterior Chain",
    # Horizontal Push
    "chest": "Horizontal Push",
    # Horizontal Pull
    "upper_back": "Horizontal Pull",
    "upper back": "Horizontal Pull",
    "lats": "Horizontal Pull",
    "middle_back": "Horizontal Pull",
    "middle back": "Horizontal Pull",
    # Vertical Pull (overridden by exercise name patterns below)
    # Vertical Push (overridden by exercise name patterns below)
    # Isolation
    "biceps": "Isolation",
    "triceps": "Isolation",
    "forearms": "Isolation",
    "calves": "Isolation",
    "abdominals": "Isolation",
    "abs": "Isolation",
    "core": "Isolation",
    "neck": "Isolation",
    "traps": "Isolation",
    "shoulders": "Vertical Push",  # default; overridden for rows
    "other": "Isolation",
}

# Exercise name patterns that override the muscle group tag
# These distinguish vertical vs horizontal movements
EXERCISE_OVERRIDES = {
    # Vertical Pull patterns
    "pull-up": "Vertical Pull",
    "pullup": "Vertical Pull",
    "pull up": "Vertical Pull",
    "chin-up": "Vertical Pull",
    "chinup": "Vertical Pull",
    "chin up": "Vertical Pull",
    "lat pulldown": "Vertical Pull",
    "pulldown": "Vertical Pull",
    # Vertical Push patterns
    "overhead press": "Vertical Push",
    "ohp": "Vertical Push",
    "military press": "Vertical Push",
    "shoulder press": "Vertical Push",
    "machine shoulder": "Vertical Push",
    "arnold press": "Vertical Push",
    "push press": "Vertical Push",
    "pike push": "Vertical Push",
    "handstand": "Vertical Push",
    "lateral raise": "Isolation",
    "front raise": "Isolation",
    "rear delt": "Isolation",
    "face pull": "Isolation",
    # Horizontal Pull (override lats if it's a row)
    "barbell row": "Horizontal Pull",
    "dumbbell row": "Horizontal Pull",
    "cable row": "Horizontal Pull",
    "seated row": "Horizontal Pull",
    "chest-supported row": "Horizontal Pull",
    "t-bar row": "Horizontal Pull",
    "pendlay row": "Horizontal Pull",
    # Posterior Chain overrides
    "deadlift": "Posterior Chain",
    "romanian deadlift": "Posterior Chain",
    "rdl": "Posterior Chain",
    "leg curl": "Posterior Chain",
    "hip thrust": "Posterior Chain",
    "good morning": "Posterior Chain",
    # Quad overrides
    "squat": "Quads",
    "leg press": "Quads",
    "hack squat": "Quads",
    "leg extension": "Quads",
    "lunge": "Quads",
    "split squat": "Quads",
    "front squat": "Quads",
    "goblet squat": "Quads",
}


def classify_muscle_group(exercise_title: str, hevy_muscle_tag: str) -> str:
    """Map an exercise to the 7-group taxonomy.

    1. Check exercise name against override patterns (handles vertical/horizontal split)
    2. Fall back to Hevy's muscle tag mapped through MUSCLE_GROUP_MAP
    3. Default to Isolation for anything unmapped
    """
    title_lower = exercise_title.lower()

    # Check exercise name overrides first (most specific)
    for pattern, group in EXERCISE_OVERRIDES.items():
        if pattern in title_lower:
            return group

    # Fall back to Hevy's muscle group tag
    tag_lower = hevy_muscle_tag.lower().strip() if hevy_muscle_tag else ""
    return MUSCLE_GROUP_MAP.get(tag_lower, "Isolation")


def epley_1rm(weight: float, reps: int) -> float:
    """Estimate 1RM using Epley formula. Only valid for reps 1-10."""
    if reps <= 0 or weight <= 0:
        return 0.0
    if reps == 1:
        return weight
    return round(weight * (1 + reps / 30), 1)


class HevyClient:
    """Fetches workout data from the Hevy App REST API."""

    def __init__(self, api_key: str | None = None):
        api_key = api_key or os.environ["HEVY_API_KEY"]
        self._headers = {"api-key": api_key, "Content-Type": "application/json"}

    def _get(self, endpoint: str, params: dict | None = None) -> dict:
        url = f"{HEVY_BASE_URL}{endpoint}"
        response = requests.get(url, headers=self._headers, params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    def fetch_workouts(self, start: datetime.date, end: datetime.date) -> list[dict]:
        """Return all workouts whose start_time falls within [start, end]."""
        utc = datetime.timezone.utc
        start_dt = datetime.datetime.combine(start, datetime.time.min, tzinfo=utc)
        end_dt = datetime.datetime.combine(end, datetime.time.max, tzinfo=utc)

        workouts = []
        page = 1
        while True:
            data = self._get("/v1/workouts", params={"page": page, "pageSize": PAGE_SIZE})
            batch = data.get("workouts", [])
            if not batch:
                break

            done = False
            for workout in batch:
                raw_time = workout.get("start_time") or workout.get("created_at", "")
                try:
                    workout_dt = datetime.datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    continue

                if workout_dt < start_dt:
                    done = True
                    break
                if workout_dt <= end_dt:
                    workouts.append(workout)

            if done:
                break
            page += 1

        return workouts

    def fetch_exercise_templates(self) -> dict[str, str]:
        """Return a dict mapping exercise_template_id -> primary muscle group name."""
        templates: dict[str, str] = {}
        page = 1
        while True:
            try:
                data = self._get("/v1/exercise_templates", params={"page": page, "pageSize": 100})
            except requests.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 404:
                    break
                raise
            batch = data.get("exercise_templates", [])
            if not batch:
                break
            for t in batch:
                tid = t.get("id")
                muscle = (
                    t.get("primary_muscle_group")
                    or t.get("muscle_group")
                    or t.get("category")
                )
                if tid and muscle:
                    templates[tid] = muscle
            page += 1
        return templates

    def summarise_workouts(
        self,
        workouts: list[dict],
        period_days: int = 7,
        template_lookup: dict[str, str] | None = None,
        primary_lifts: list[str] | None = None,
    ) -> dict:
        """Compute training summary aligned with proposal Section 4.2.

        Returns:
        - workout_count: total sessions
        - workout_dates: list of dates
        - sets_per_muscle_group: {group: count} — primary volume metric
        - volume_load_per_muscle_group: {group: total_kg*reps} — progressive overload metric
        - primary_lift_top_sets: {lift_name: {weight_kg, reps, estimated_1rm}}
        - exercises: per-exercise breakdown
        """
        if not workouts:
            return {
                "workout_count": 0,
                "workout_dates": [],
                "sets_per_muscle_group": {},
                "volume_load_per_muscle_group": {},
                "primary_lift_top_sets": {},
                "exercises": {},
            }

        primary_lifts_lower = {l.lower() for l in (primary_lifts or [])}

        workout_dates = []
        sets_by_group: dict[str, int] = {}
        volume_by_group: dict[str, float] = {}
        primary_top_sets: dict[str, dict] = {}
        exercises_summary: dict[str, dict] = {}

        for workout in workouts:
            raw_time = workout.get("start_time") or workout.get("created_at", "")
            try:
                dt = datetime.datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
                workout_dates.append(dt.strftime(DATE_FORMAT))
            except (ValueError, AttributeError):
                pass

            for ex in workout.get("exercises", []):
                title = ex.get("title") or ex.get("exercise_template_id", "Unknown")
                template_id = ex.get("exercise_template_id")
                raw_muscle = (
                    (template_lookup.get(template_id) if template_lookup and template_id else None)
                    or ex.get("primary_muscle_group")
                    or ex.get("muscle_group")
                    or ex.get("category")
                    or "Other"
                )

                muscle_group = classify_muscle_group(title, raw_muscle)

                sets = ex.get("sets", [])
                working_set_count = 0

                for s in sets:
                    weight = float(s.get("weight_kg") or s.get("weight") or 0)
                    reps = int(s.get("reps") or 0)
                    set_type = s.get("type", "normal")

                    # Count working sets (exclude warmup sets)
                    if set_type != "warmup" and reps > 0:
                        working_set_count += 1

                    volume = weight * reps

                    # Volume load per group
                    volume_by_group[muscle_group] = volume_by_group.get(muscle_group, 0.0) + volume

                    # Track primary lift top sets
                    title_lower = title.lower()
                    for lift in primary_lifts_lower:
                        if lift in title_lower and weight > 0 and reps > 0:
                            current = primary_top_sets.get(title)
                            if not current or weight > current["weight_kg"]:
                                primary_top_sets[title] = {
                                    "weight_kg": weight,
                                    "reps": reps,
                                    "estimated_1rm": epley_1rm(weight, reps),
                                }

                    # Per-exercise summary
                    if title not in exercises_summary:
                        exercises_summary[title] = {
                            "muscle_group": muscle_group,
                            "total_sets": 0,
                            "total_reps": 0,
                            "max_weight_kg": 0.0,
                        }
                    if reps > 0:
                        exercises_summary[title]["total_sets"] += 1
                    exercises_summary[title]["total_reps"] += reps
                    exercises_summary[title]["max_weight_kg"] = max(
                        exercises_summary[title]["max_weight_kg"], weight
                    )

                # Sets per muscle group (working sets only)
                sets_by_group[muscle_group] = sets_by_group.get(muscle_group, 0) + working_set_count

        return {
            "workout_count": len(workouts),
            "workout_dates": sorted(set(workout_dates)),
            "sets_per_muscle_group": dict(sorted(sets_by_group.items(), key=lambda x: -x[1])),
            "volume_load_per_muscle_group": {
                k: round(v, 1)
                for k, v in sorted(volume_by_group.items(), key=lambda x: -x[1])
            },
            "primary_lift_top_sets": primary_top_sets,
            "exercises": exercises_summary,
        }
