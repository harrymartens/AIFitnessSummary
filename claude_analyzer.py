import json

import anthropic

from config import MAX_TOKENS, MODEL

SYSTEM_PROMPT = """\
You are an expert personal fitness coach and health analyst. You will be given \
structured fitness and health data covering a specific review period. Your job is \
to analyse the data and produce a clear, insightful, and actionable fitness review.

Write in a warm, motivating, but honest tone. Be specific — reference the actual \
numbers from the data. Avoid generic advice; tailor every recommendation to what \
the data shows.

Structure your response with these exact Markdown headings (in this order):
## Executive Summary
## Activity & Cardiovascular Highlights
## Sleep Quality
## Recovery & Stress
## Strength Training Analysis
## Training Load Assessment
## Recommendations for Next Period

Keep the total response under 1200 words. Use bullet points where appropriate for \
clarity. Do not repeat raw data tables — those appear separately in the report.\
"""


def _format_data_for_prompt(
    period: str,
    start_date: str,
    end_date: str,
    garmin: dict,
    hevy: dict,
) -> str:
    lines = [
        f"REVIEW PERIOD: {period.upper()} ({start_date} to {end_date})",
        "",
        "=== GARMIN HEALTH DATA ===",
        "",
        "-- Activity --",
        f"Average daily steps: {garmin['stats'].get('avg_daily_steps')}",
        f"Average daily distance: {garmin['stats'].get('avg_distance_km')} km",
        f"Average daily active minutes: {garmin['stats'].get('avg_active_minutes')}",
        f"Average intensity minutes: {garmin['stats'].get('avg_intensity_minutes')}",
        f"Average floors climbed/day: {garmin['stats'].get('avg_floors')}",
        f"Average total calories/day: {garmin['stats'].get('avg_total_calories')} kcal",
        "",
        "-- Cardiovascular --",
        f"Average resting heart rate: {garmin['heart_rate'].get('avg_resting_hr')} bpm",
        "Daily resting HR trend (date: bpm):",
    ]
    for entry in garmin["heart_rate"].get("daily_trend", []):
        lines.append(f"  {entry['date']}: {entry['resting_hr']} bpm")

    lines += [
        "",
        "-- HRV --",
        f"Period average HRV: {garmin['hrv'].get('period_avg_ms')} ms",
        "Daily HRV status:",
    ]
    for entry in garmin["hrv"].get("daily", []):
        lines.append(f"  {entry['date']}: {entry.get('status', 'n/a')} (last night avg: {entry.get('last_night_avg_ms')} ms)")

    spo2 = garmin.get("spo2", {})
    resp = garmin.get("respiration", {})
    vo2 = garmin.get("vo2max", {})
    lines += [
        "",
        "-- Blood Oxygen & Respiration --",
        f"Average SpO2: {spo2.get('avg_spo2')} %",
        f"Average lowest nightly SpO2: {spo2.get('avg_lowest_spo2')} %",
        f"Average waking respiration rate: {resp.get('avg_waking_brpm')} brpm",
        f"Average sleep respiration rate: {resp.get('avg_sleep_brpm')} brpm",
        "",
        "-- VO2 Max & Fitness Age --",
        f"VO2 max: {vo2.get('vo2_max')} ml/kg/min",
        f"Fitness age: {vo2.get('fitness_age')} yrs",
    ]

    lines += [
        "",
        "-- Sleep --",
        f"Average total sleep: {garmin['sleep'].get('avg_total_h')} h",
        f"Average deep sleep: {garmin['sleep'].get('avg_deep_h')} h",
        f"Average REM sleep: {garmin['sleep'].get('avg_rem_h')} h",
        f"Average light sleep: {garmin['sleep'].get('avg_light_h')} h",
        f"Average awake time: {garmin['sleep'].get('avg_awake_h')} h",
        f"Nights tracked: {len(garmin['sleep'].get('nightly', []))}",
        "Nightly breakdown:",
    ]
    for night in garmin["sleep"].get("nightly", []):
        lines.append(
            f"  {night['date']}: total {night['total_h']}h | deep {night['deep_h']}h | "
            f"REM {night['rem_h']}h | light {night['light_h']}h | awake {night['awake_h']}h"
        )

    readiness = garmin.get("training_readiness", {})
    lines += [
        "",
        "-- Stress, Recovery & Body Battery --",
        f"Average stress level: {garmin['stress'].get('avg_stress')} (0–100 scale)",
        "Daily stress (date: score):",
    ]
    for entry in garmin["stress"].get("daily", []):
        lines.append(f"  {entry['date']}: {entry['avg_stress']}")
    lines += [
        f"Average body battery max (charged): {garmin['body_battery'].get('avg_max')}",
        f"Average body battery drain: {garmin['body_battery'].get('avg_min')}",
        f"Average training readiness score: {readiness.get('avg_score')} / 100",
        f"Latest training readiness: {readiness.get('latest_score')} ({readiness.get('latest_level')})",
        "Daily training readiness (date: score / level):",
    ]
    for entry in readiness.get("daily", []):
        lines.append(f"  {entry['date']}: {entry['score']} / {entry.get('level', 'n/a')}")

    lines += [
        "",
        "-- Training Load --",
        f"Average training load: {garmin['training_load'].get('avg_load')}",
        f"Latest training status: {garmin['training_load'].get('latest_status')}",
    ]

    body = garmin.get("body_composition", {})
    if body.get("latest_weight_kg"):
        lines += [
            "",
            "-- Body Composition --",
            f"Latest weight: {body.get('latest_weight_kg')} kg",
            f"Average weight: {body.get('avg_weight_kg')} kg",
            f"Latest BMI: {body.get('latest_bmi')}",
            f"Latest body fat: {body.get('latest_body_fat_pct')} %",
        ]

    runs = garmin.get("runs", {})
    if runs.get("run_count"):
        lines += [
            "",
            "-- Running --",
            f"Runs completed: {runs['run_count']}",
            f"Total distance: {runs['total_distance_km']} km",
            f"Average pace: {runs.get('avg_pace_min_km')} min/km",
            "Individual runs (date: distance km, pace min/km, avg HR):",
        ]
        for r in runs.get("runs", []):
            lines.append(
                f"  {r['date']}: {r['distance_km']} km @ {r.get('avg_pace_min_km')} min/km"
                + (f", HR {r['avg_hr']} bpm" if r.get("avg_hr") else "")
            )

    lines += [
        "",
        "=== HEVY STRENGTH TRAINING DATA ===",
        "",
        f"Workouts completed: {hevy.get('workout_count')}",
        f"Workouts per week: {hevy.get('workouts_per_week')}",
        f"Training dates: {', '.join(hevy.get('workout_dates', []))}",
        "",
        "Volume by muscle group (kg × reps):",
    ]
    for muscle, vol in hevy.get("volume_by_muscle_group", {}).items():
        lines.append(f"  {muscle}: {vol}")

    if hevy.get("personal_records"):
        lines.append("")
        lines.append("Personal records set this period:")
        for pr in hevy["personal_records"]:
            lines.append(f"  {pr['exercise']}: {pr['weight_kg']} kg × {pr['reps']} reps")

    lines += [
        "",
        "Exercise breakdown (sets / max weight):",
    ]
    for name, ex in hevy.get("exercises", {}).items():
        lines.append(
            f"  {name} [{ex['muscle_group']}]: {ex['total_sets']} sets, "
            f"{ex['total_reps']} reps, max {ex['max_weight_kg']} kg"
        )

    return "\n".join(lines)


class ClaudeAnalyzer:
    """Uses the Anthropic API to generate a narrative fitness review."""

    def __init__(self):
        self._client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

    def generate_review(
        self,
        period: str,
        start_date: str,
        end_date: str,
        garmin_data: dict,
        hevy_summary: dict,
    ) -> str:
        user_content = _format_data_for_prompt(period, start_date, end_date, garmin_data, hevy_summary)

        print("Generating Claude analysis…")
        response = self._client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        return response.content[0].text
