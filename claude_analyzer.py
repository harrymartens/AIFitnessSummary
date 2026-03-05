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
        "-- VO2 Max, Fitness Age & Performance --",
        f"VO2 max: {vo2.get('vo2_max')} ml/kg/min",
    ]

    fa = garmin.get("fitness_age", {})
    lt = garmin.get("lactate_threshold", {})
    es = garmin.get("endurance_score", {})
    rp = garmin.get("race_predictions", {})
    lines += [
        f"Fitness age: {fa.get('fitness_age')} yrs (chronological: {fa.get('chronological_age')}, achievable: {fa.get('achievable_fitness_age')})",
        f"Endurance score: {es.get('score')} ({es.get('classification')})",
        f"Lactate threshold HR: {lt.get('lt_heart_rate')} bpm | Running FTP: {lt.get('ftp_watts')} W",
    ]
    if any(rp.get(k) for k in ("time_5k", "time_10k", "time_half", "time_marathon")):
        lines += [
            "Predicted race times:",
            f"  5K: {rp.get('time_5k')} | 10K: {rp.get('time_10k')} | Half: {rp.get('time_half')} | Marathon: {rp.get('time_marathon')}",
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
    mr = garmin.get("morning_readiness", {})
    sweat = garmin.get("sweat_loss", {})
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
        f"Average morning readiness score: {mr.get('avg_score') or readiness.get('avg_score')} / 100",
        f"Latest morning readiness: {mr.get('latest_score') or readiness.get('latest_score')} ({mr.get('latest_level') or readiness.get('latest_level')})",
        f"Average daily sweat loss: {sweat.get('avg_sweat_loss_ml')} mL",
        "Morning readiness detail (date: score / level / sleep-score / recovery-h / HRV-factor%):",
    ]
    for d in mr.get("daily", []):
        lines.append(
            f"  {d['date']}: {d.get('score')} / {d.get('level')} | "
            f"sleep {d.get('sleep_score')} | recovery {d.get('recovery_time_h')}h | "
            f"HRV factor {d.get('hrv_factor_pct')}%"
        )

    tl = garmin["training_load"]
    lines += [
        "",
        "-- Training Load --",
        f"Training status: {tl.get('status_phrase')}",
        f"Acute load: {tl.get('acute_load')} | Chronic load: {tl.get('chronic_load')}",
        f"ACWR ratio: {tl.get('acwr_ratio')} ({tl.get('acwr_status')} — 0.8–1.3 is optimal)",
        f"Load balance: {tl.get('balance_phrase')}",
        f"Monthly aerobic-low: {tl.get('aerobic_low')} | aerobic-high: {tl.get('aerobic_high')} | anaerobic: {tl.get('anaerobic')}",
    ]

    weekly = garmin.get("weekly_intensity", {})
    if weekly.get("weeks"):
        lines.append("Weekly intensity minutes (moderate / vigorous / total-equiv / goal / met?):")
        for w in weekly["weeks"]:
            lines.append(
                f"  {w['week_start']}: {w['moderate_min']}min mod + {w['vigorous_min']}min vig"
                f" = {w['total_equivalent_min']}min equiv vs {w['goal_min']}min goal"
                f" ({'MET' if w['met_goal'] else 'NOT MET'})"
            )

    hs = garmin.get("hill_score", {})
    if hs.get("overall_score") is not None:
        lines.append(
            f"Hill score: {hs['overall_score']} overall "
            f"(strength {hs.get('strength_score')}, endurance {hs.get('endurance_score')})"
        )

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
            "Individual runs (date: distance, pace, avg HR, cadence, power, GCT):",
        ]
        for r in runs.get("runs", []):
            dyn = r.get("running_dynamics", {})
            zones = r.get("hr_zones", {})
            run_line = (
                f"  {r['date']}: {r['distance_km']} km @ {r.get('avg_pace_min_km')} min/km"
                + (f", HR {r['avg_hr']} bpm" if r.get("avg_hr") else "")
                + (f", cadence {dyn['avg_cadence_spm']} spm" if dyn.get("avg_cadence_spm") else "")
                + (f", power {dyn['avg_power_w']} W" if dyn.get("avg_power_w") else "")
                + (f", GCT {dyn['avg_ground_contact_ms']} ms" if dyn.get("avg_ground_contact_ms") else "")
            )
            lines.append(run_line)
            if zones:
                z1 = zones.get("zone1_pct", 0)
                z2 = zones.get("zone2_pct", 0)
                z3 = zones.get("zone3_pct", 0)
                z4 = zones.get("zone4_pct", 0)
                z5 = zones.get("zone5_pct", 0)
                lines.append(
                    f"    HR zones: Z1 {z1}% | Z2 {z2}% | Z3 {z3}% | Z4 {z4}% | Z5 {z5}%"
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
