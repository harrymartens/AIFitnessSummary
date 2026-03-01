import datetime
import os

import requests

from config import DATE_FORMAT

HEVY_BASE_URL = "https://api.hevyapp.com"
PAGE_SIZE = 10  # Hevy API maximum


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
                # Hevy returns ISO 8601; normalise 'Z' → '+00:00' for fromisoformat
                try:
                    workout_dt = datetime.datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    continue

                if workout_dt < start_dt:
                    # Workouts are returned newest-first; once we're before start, stop
                    done = True
                    break
                if workout_dt <= end_dt:
                    workouts.append(workout)

            if done:
                break
            page += 1

        return workouts

    def summarise_workouts(self, workouts: list[dict], period_days: int = 7) -> dict:
        """Compute training summary from a list of Hevy workout objects."""
        if not workouts:
            return {
                "workout_count": 0,
                "workouts_per_week": 0.0,
                "workout_dates": [],
                "volume_by_muscle_group": {},
                "exercises": {},
                "personal_records": [],
            }

        workout_dates = []
        volume_by_muscle = {}
        exercise_maxes: dict[str, float] = {}  # exercise title → max weight seen
        personal_records = []
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
                muscle_group = (
                    ex.get("muscle_group")
                    or ex.get("primary_muscle_group")
                    or ex.get("category")
                    or "Other"
                )

                sets = ex.get("sets", [])
                for s in sets:
                    weight = s.get("weight_kg") or s.get("weight") or 0
                    reps = s.get("reps") or 0
                    volume = float(weight) * int(reps)

                    # Accumulate volume by muscle group
                    volume_by_muscle[muscle_group] = volume_by_muscle.get(muscle_group, 0.0) + volume

                    # Track max weight per exercise for PR detection
                    current_max = exercise_maxes.get(title, 0.0)
                    if float(weight) > current_max:
                        if current_max > 0:  # only flag as PR if there was a previous record in period
                            personal_records.append({
                                "exercise": title,
                                "weight_kg": float(weight),
                                "reps": reps,
                            })
                        exercise_maxes[title] = float(weight)

                    # Exercises summary
                    if title not in exercises_summary:
                        exercises_summary[title] = {
                            "muscle_group": muscle_group,
                            "total_sets": 0,
                            "total_reps": 0,
                            "max_weight_kg": 0.0,
                        }
                    exercises_summary[title]["total_sets"] += 1
                    exercises_summary[title]["total_reps"] += reps
                    exercises_summary[title]["max_weight_kg"] = max(
                        exercises_summary[title]["max_weight_kg"], float(weight)
                    )

        weeks = period_days / 7
        return {
            "workout_count": len(workouts),
            "workouts_per_week": round(len(workouts) / weeks, 1),
            "workout_dates": sorted(set(workout_dates)),
            "volume_by_muscle_group": {
                k: round(v, 1)
                for k, v in sorted(volume_by_muscle.items(), key=lambda x: -x[1])
            },
            "exercises": exercises_summary,
            "personal_records": personal_records,
        }
