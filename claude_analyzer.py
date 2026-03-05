import json
import re

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
clarity. Do not repeat raw data tables — those appear separately in the report.

GOAL-AWARE ANALYSIS:
- The user's active fitness goal is provided in the [ACTIVE GOAL] section of the prompt.
- Frame ALL observations relative to this goal. Every section should answer: "How does this metric relate to the goal?"
- If a metric is on-track toward the goal, say so explicitly with the data to back it up.
- If a metric is off-track, identify it clearly and connect it to goal impact.
- If the goal is marked as "Provisional (AI-inferred)", note this and invite the user to confirm or update it via: python main.py goals
- If no goal is provided, note that no goal is set and recommend running: python main.py goals

RECOMMENDATIONS FORMAT:
At the end of your response, after all narrative sections, output a structured block in this exact format:

---RECOMMENDATIONS---
[HIGH] category: text of recommendation
[MEDIUM] category: text of recommendation
[LOW] category: text of recommendation
---END RECOMMENDATIONS---

- Include 3–5 recommendations total
- Priority: HIGH, MEDIUM, or LOW
- Category must be one of: sleep, training, recovery, cardiovascular, nutrition, general
- Text should be specific and actionable, referencing actual numbers from the data
- This block must appear AFTER the narrative sections so it does not disrupt the report flow

EVIDENCE-BASED GUIDANCE:
- If a [KNOWLEDGE BASE] section is provided, draw on it to support your recommendations.
- If a [RESEARCH CONTEXT] section is provided, cite the specific source by name (e.g. "According to [Source Name]...").
- Distinguish evidence-based claims from general coaching guidance.
- Do not fabricate citations. Only cite sources that appear in the provided context blocks.\
"""


def _format_goal_for_prompt(goal: dict) -> str:
    """Format a goal dict into a prompt block."""
    lines = ["[ACTIVE GOAL]"]
    lines.append(f"Goal: {goal.get('goal_type', 'Unknown')}")
    if goal.get("description"):
        lines.append(f"Description: {goal['description']}")
    if goal.get("target_date"):
        lines.append(f"Target date: {goal['target_date']}")
    if goal.get("provisional"):
        lines.append("Status: Provisional (AI-inferred)")
    else:
        lines.append("Status: Confirmed")
    return "\n".join(lines)


def _format_data_for_prompt(
    period: str,
    start_date: str,
    end_date: str,
    garmin: dict,
    hevy: dict,
    goal=None,
    trend_context=None,
    active_recommendations=None,
    knowledge_context=None,
) -> str:
    lines = []

    # 1. Goal block (if available)
    if goal:
        try:
            from goal_manager import format_goal_for_prompt as _ext_fmt
            lines.append(_ext_fmt(goal))
        except Exception:
            lines.append(_format_goal_for_prompt(goal))
        lines.append("")
    else:
        lines.append("[ACTIVE GOAL]\nNo active goal set. Run: python main.py goals")
        lines.append("")

    # 2. Historical trend context (if available)
    if trend_context:
        lines.append(trend_context)
        lines.append("")

    # 3. Previous recommendations (if available)
    if active_recommendations:
        lines.append("[PREVIOUS RECOMMENDATIONS — PLEASE ASSESS EACH]")
        for rec in active_recommendations:
            priority_label = {1: "HIGH", 2: "MEDIUM", 3: "LOW"}.get(rec.get("priority", 2), "MEDIUM")
            lines.append(f"[{priority_label}] [{rec.get('category', 'general').upper()}] {rec.get('text', '')}")
        lines.append("For each recommendation above, assess: CONTINUED | ESCALATED | RESOLVED")
        lines.append("Include your assessment in the Recommendations section of your response.")
        lines.append("")

    # 4. Knowledge context (if available)
    if knowledge_context:
        lines.append(knowledge_context)
        lines.append("")

    # Existing period + Garmin + Hevy content
    lines += [
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
        goal: dict | None = None,
        trend_context: str | None = None,
        active_recommendations: list | None = None,
        knowledge_context: str | None = None,
    ) -> str:
        user_content = _format_data_for_prompt(
            period,
            start_date,
            end_date,
            garmin_data,
            hevy_summary,
            goal=goal,
            trend_context=trend_context,
            active_recommendations=active_recommendations,
            knowledge_context=knowledge_context,
        )

        print("Generating Claude analysis…")
        response = self._client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        return response.content[0].text

    @staticmethod
    def parse_recommendations(response: str) -> list[dict]:
        """
        Extract structured recommendations from Claude's response.
        Returns list of dicts: {"priority": int, "category": str, "text": str}
        Priority: HIGH=1, MEDIUM=2, LOW=3
        Returns [] if no recommendations block found.
        """
        pattern = r'---RECOMMENDATIONS---(.*?)---END RECOMMENDATIONS---'
        match = re.search(pattern, response, re.DOTALL)
        if not match:
            return []

        block = match.group(1).strip()
        recommendations = []
        priority_map = {"HIGH": 1, "MEDIUM": 2, "LOW": 3}

        for line in block.splitlines():
            line = line.strip()
            if not line:
                continue
            # Match: [HIGH] category: text
            m = re.match(r'\[(HIGH|MEDIUM|LOW)\]\s+(\w+):\s+(.+)', line)
            if m:
                recommendations.append({
                    "priority": priority_map.get(m.group(1), 2),
                    "category": m.group(2).lower(),
                    "text": m.group(3).strip()
                })

        return recommendations

    @staticmethod
    def strip_recommendations_block(response: str) -> str:
        """Remove the ---RECOMMENDATIONS--- block from response before saving to report."""
        return re.sub(r'\n*---RECOMMENDATIONS---.*?---END RECOMMENDATIONS---\n*',
                      '', response, flags=re.DOTALL).strip()
