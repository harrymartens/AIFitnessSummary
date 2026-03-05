import datetime
from pathlib import Path

from config import DATE_FORMAT, REPORT_DIR


def _h(level: int, text: str) -> str:
    return f"{'#' * level} {text}"


def _table(headers: list[str], rows: list[list]) -> str:
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))

    def fmt_row(cells):
        return "| " + " | ".join(str(c).ljust(col_widths[i]) for i, c in enumerate(cells)) + " |"

    sep = "| " + " | ".join("-" * w for w in col_widths) + " |"
    return "\n".join([fmt_row(headers), sep] + [fmt_row(r) for r in rows])


class ReportGenerator:
    """Assembles raw metric data and Claude's narrative into a Markdown report."""

    def generate(
        self,
        period: str,
        start_date: datetime.date,
        end_date: datetime.date,
        garmin_data: dict,
        hevy_summary: dict,
        claude_narrative: str,
        goal: dict = None,
        trend_context_str: str = None,
        followup_summary_str: str = None,
    ) -> Path:
        REPORT_DIR.mkdir(exist_ok=True)
        filename = f"{period}_review_{end_date.strftime(DATE_FORMAT)}.md"
        output_path = REPORT_DIR / filename

        sections = self._build_sections(
            period, start_date, end_date, garmin_data, hevy_summary, claude_narrative,
            goal=goal,
            trend_context_str=trend_context_str,
            followup_summary_str=followup_summary_str,
        )
        output_path.write_text("\n\n".join(sections), encoding="utf-8")
        return output_path

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _build_sections(
        self,
        period: str,
        start: datetime.date,
        end: datetime.date,
        garmin: dict,
        hevy: dict,
        narrative: str,
        goal: dict = None,
        trend_context_str: str = None,
        followup_summary_str: str = None,
    ) -> list[str]:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        header = "\n".join([
            f"# {period.capitalize()} Fitness Review — {end.strftime('%B %d, %Y')}",
            "",
            f"**Period:** {start.strftime(DATE_FORMAT)} → {end.strftime(DATE_FORMAT)}  ",
            f"**Generated:** {now}  ",
            f"**Sources:** Garmin Connect · Hevy App · Claude (`claude-sonnet-4-6`)  ",
        ])

        # Split Claude narrative into labelled sections
        narrative_sections = self._split_narrative(narrative)

        sections = [header]

        # Executive Summary from Claude
        sections.append(narrative_sections.get(
            "Executive Summary",
            _h(2, "Executive Summary") + "\n\n_No summary generated._"
        ))

        # Goal Progress (immediately after Executive Summary)
        sections.append(self._section_goal_progress(goal, garmin, hevy))

        # Activity Overview (raw data table)
        sections.append(self._section_activity(garmin["stats"]))

        # Cardiovascular Health
        sections.append(self._section_cardio(
            garmin["heart_rate"], garmin["hrv"],
            garmin.get("spo2", {}), garmin.get("respiration", {}), garmin.get("vo2max", {}),
        ))

        # Sleep Analysis
        sections.append(self._section_sleep(garmin["sleep"]))

        # Recovery & Stress
        sections.append(self._section_recovery(
            garmin["stress"], garmin["body_battery"], garmin.get("training_readiness", {})
        ))

        # Body Metrics (only if data available)
        body_section = self._section_body(garmin.get("body_composition", {}))
        if body_section:
            sections.append(body_section)

        # Progress Over Time (trend overview — after Body Metrics, before Strength Training)
        trend_section = self._section_trend_overview(trend_context_str)
        if trend_section:
            sections.append(trend_section)

        # Strength Training (Hevy)
        sections.append(self._section_strength(hevy))

        # Running (Garmin)
        sections.append(self._section_runs(garmin.get("runs", {})))

        # Training Load
        sections.append(self._section_training_load(garmin["training_load"]))

        # Claude's full narrative (minus the Executive Summary which is shown first)
        insights_key = "Recommendations for Next Period"
        insights = narrative_sections.get(insights_key, "")
        remaining = self._narrative_minus_exec(narrative)
        sections.append(_h(2, "Claude's Insights & Recommendations") + "\n\n" + remaining)

        # Recommendation Follow-up (after Claude's Insights & Recommendations)
        followup_section = self._section_recommendation_followup(followup_summary_str)
        if followup_section:
            sections.append(followup_section)

        return sections

    def _section_goal_progress(self, goal: dict, garmin_data: dict, hevy_data: dict) -> str:
        if not goal:
            return (
                _h(2, "Goal Progress") + "\n\n"
                "_No active goal set. Run `python main.py goals` to set one._"
            )

        objective = goal.get("primary_objective", "N/A")
        timeline_weeks = goal.get("timeline_weeks")
        is_provisional = goal.get("is_provisional", 0)
        status_label = "Provisional (unconfirmed)" if is_provisional else "Active (Confirmed)"

        header_parts = [f"**Objective:** {objective}"]
        if timeline_weeks is not None:
            header_parts[0] += f" — {timeline_weeks} weeks remaining"
        header_parts.append(f"**Status:** {status_label}")

        # Gather current metrics from garmin/hevy data
        stats = garmin_data.get("stats", {})
        sleep = garmin_data.get("sleep", {})
        hr = garmin_data.get("heart_rate", {})
        body = garmin_data.get("body_composition", {})
        current_weight = body.get("latest_weight_kg")
        current_steps = stats.get("avg_daily_steps")
        current_sleep = sleep.get("avg_total_h")
        current_workouts = hevy_data.get("workouts_per_week")
        current_resting_hr = hr.get("avg_resting_hr")

        rows = []

        # Weight
        target_weight = goal.get("target_weight_kg")
        if target_weight is not None and current_weight is not None:
            diff = current_weight - target_weight
            pct = current_weight / target_weight if target_weight else None
            if diff <= 0:
                icon = "🟢"
                note = "On target"
            elif pct is not None and pct <= 1.10:
                icon = "🟡"
                note = f"+{diff:.1f} kg to go"
            else:
                icon = "🔴"
                note = f"+{diff:.1f} kg to go"
            rows.append(["Weight", f"{target_weight} kg", f"{current_weight} kg", f"{icon} {note}"])

        # Daily Steps
        target_steps = goal.get("target_steps_per_day")
        if target_steps is not None and current_steps is not None:
            pct = current_steps / target_steps if target_steps else None
            if pct is not None and pct >= 0.95:
                icon = "🟢"
                note = "On target"
            elif pct is not None and pct >= 0.85:
                icon = "🟡"
                note = f"{pct * 100:.0f}% of target"
            else:
                icon = "🔴"
                note = f"{pct * 100:.0f}% of target" if pct is not None else "Below target"
            rows.append(["Daily Steps", f"{target_steps:,}", f"{int(current_steps):,}", f"{icon} {note}"])

        # Sleep
        target_sleep = goal.get("target_sleep_hours")
        if target_sleep is not None and current_sleep is not None:
            pct = current_sleep / target_sleep if target_sleep else None
            if pct is not None and pct >= 0.95:
                icon = "🟢"
                note = "On target"
            elif pct is not None and pct >= 0.85:
                icon = "🟡"
                note = f"{pct * 100:.0f}% of target"
            else:
                icon = "🔴"
                note = f"{pct * 100:.0f}% of target" if pct is not None else "Below target"
            rows.append(["Sleep", f"{target_sleep} hrs", f"{current_sleep} hrs", f"{icon} {note}"])

        # Workouts/Week
        target_workouts = goal.get("target_workouts_per_week")
        if target_workouts is not None and current_workouts is not None:
            pct = current_workouts / target_workouts if target_workouts else None
            if pct is not None and pct >= 0.95:
                icon = "🟢"
                note = "On target"
            elif pct is not None and pct >= 0.85:
                icon = "🟡"
                note = f"{pct * 100:.0f}% of target"
            else:
                icon = "🔴"
                note = f"{pct * 100:.0f}% of target" if pct is not None else "Below target"
            rows.append(["Workouts/Week", str(target_workouts), str(current_workouts), f"{icon} {note}"])

        # Resting HR (lower is better — invert the ratio)
        target_hr = goal.get("target_resting_hr")
        if target_hr is not None and current_resting_hr is not None:
            # For HR, current <= target is good; current much higher than target is bad
            diff_pct = (current_resting_hr - target_hr) / target_hr if target_hr else 0
            if diff_pct <= 0.05:
                icon = "🟢"
                note = "On target"
            elif diff_pct <= 0.15:
                icon = "🟡"
                note = "Close"
            else:
                icon = "🔴"
                note = f"{current_resting_hr - target_hr:+.0f} bpm off target"
            rows.append(["Resting HR", f"{target_hr} bpm", f"{current_resting_hr} bpm", f"{icon} {note}"])

        lines = [_h(2, "Goal Progress"), ""]
        lines.extend(header_parts)
        lines.append("")
        if rows:
            lines.append(_table(["Metric", "Target", "Current", "Status"], rows))
        else:
            lines.append("_No comparable metrics available for this goal._")

        return "\n".join(lines)

    def _section_trend_overview(self, trend_context_str: str) -> str:
        if not trend_context_str:
            return ""
        return _h(2, "Progress Over Time") + "\n\n" + trend_context_str

    def _section_recommendation_followup(self, followup_summary_str: str) -> str:
        if not followup_summary_str:
            return ""
        return _h(2, "Recommendation Follow-up") + "\n\n" + followup_summary_str

    def _split_narrative(self, narrative: str) -> dict[str, str]:
        """Parse Claude's response into a dict keyed by section heading."""
        result: dict[str, str] = {}
        current_key = None
        current_lines: list[str] = []

        for line in narrative.splitlines():
            if line.startswith("## "):
                if current_key is not None:
                    result[current_key] = _h(2, current_key) + "\n\n" + "\n".join(current_lines).strip()
                current_key = line[3:].strip()
                current_lines = []
            else:
                current_lines.append(line)

        if current_key is not None:
            result[current_key] = _h(2, current_key) + "\n\n" + "\n".join(current_lines).strip()

        return result

    def _narrative_minus_exec(self, narrative: str) -> str:
        """Return the narrative with the Executive Summary section removed."""
        lines = narrative.splitlines()
        output = []
        in_exec = False
        for line in lines:
            if line.startswith("## Executive Summary"):
                in_exec = True
                continue
            if in_exec and line.startswith("## "):
                in_exec = False
            if not in_exec:
                output.append(line)
        return "\n".join(output).strip()

    # ------------------------------------------------------------------
    # Individual sections
    # ------------------------------------------------------------------

    def _section_activity(self, stats: dict) -> str:
        rows = [
            ["Average daily steps", _fmt(stats.get("avg_daily_steps"), "steps")],
            ["Average daily distance", _fmt(stats.get("avg_distance_km"), "km")],
            ["Average active minutes/day", _fmt(stats.get("avg_active_minutes"), "min")],
            ["Average intensity minutes/day", _fmt(stats.get("avg_intensity_minutes"), "min")],
            ["Average floors climbed/day", _fmt(stats.get("avg_floors"), "floors")],
            ["Average total calories/day", _fmt(stats.get("avg_total_calories"), "kcal")],
            ["Days with data", str(stats.get("days_with_data", "—"))],
        ]
        return _h(2, "Activity Overview") + "\n\n" + _table(["Metric", "Value"], rows)

    def _section_cardio(self, hr: dict, hrv: dict, spo2: dict, respiration: dict, vo2max: dict) -> str:
        lines = [_h(2, "Cardiovascular Health"), ""]

        rows = [
            ["Average resting heart rate", _fmt(hr.get("avg_resting_hr"), "bpm")],
            ["Period HRV average", _fmt(hrv.get("period_avg_ms"), "ms")],
            ["Average SpO2", _fmt(spo2.get("avg_spo2"), "%")],
            ["Average lowest SpO2", _fmt(spo2.get("avg_lowest_spo2"), "%")],
            ["Avg waking respiration", _fmt(respiration.get("avg_waking_brpm"), "brpm")],
            ["Avg sleep respiration", _fmt(respiration.get("avg_sleep_brpm"), "brpm")],
            ["VO2 max", _fmt(vo2max.get("vo2_max"), "ml/kg/min")],
            ["Fitness age", _fmt(vo2max.get("fitness_age"), "yrs")],
        ]
        lines.append(_table(["Metric", "Value"], rows))
        lines.append("")

        trend = hr.get("daily_trend", [])
        if trend:
            lines.append(_h(3, "Resting HR Daily Trend"))
            lines.append(_table(
                ["Date", "Resting HR (bpm)"],
                [[e["date"], e["resting_hr"]] for e in trend]
            ))

        return "\n".join(lines)

    def _section_sleep(self, sleep: dict) -> str:
        lines = [_h(2, "Sleep Analysis"), ""]
        averages = [
            ["Average total sleep", _fmt(sleep.get("avg_total_h"), "h")],
            ["Average deep sleep", _fmt(sleep.get("avg_deep_h"), "h")],
            ["Average REM sleep", _fmt(sleep.get("avg_rem_h"), "h")],
            ["Average light sleep", _fmt(sleep.get("avg_light_h"), "h")],
            ["Average awake time", _fmt(sleep.get("avg_awake_h"), "h")],
            ["Nights tracked", str(len(sleep.get("nightly", [])))],
        ]
        lines.append(_table(["Metric", "Average"], averages))
        return "\n".join(lines)

    def _section_recovery(self, stress: dict, battery: dict, readiness: dict) -> str:
        lines = [_h(2, "Recovery & Stress"), ""]
        summary = [
            ["Average stress level", _fmt(stress.get("avg_stress"), "/100")],
            ["Avg body battery charged", _fmt(battery.get("avg_max"), "pts")],
            ["Avg body battery drained", _fmt(battery.get("avg_min"), "pts")],
            ["Avg training readiness", _fmt(readiness.get("avg_score"), "/100")],
            ["Latest readiness score", _fmt(readiness.get("latest_score"), "")],
            ["Latest readiness level", readiness.get("latest_level") or "—"],
        ]
        lines.append(_table(["Metric", "Value"], summary))
        return "\n".join(lines)

    def _section_body(self, body: dict) -> str | None:
        if not body.get("latest_weight_kg"):
            return None
        rows = [
            ["Latest weight", _fmt(body.get("latest_weight_kg"), "kg")],
            ["Average weight", _fmt(body.get("avg_weight_kg"), "kg")],
            ["BMI", _fmt(body.get("latest_bmi"), "")],
            ["Body fat %", _fmt(body.get("latest_body_fat_pct"), "%")],
        ]
        return _h(2, "Body Metrics") + "\n\n" + _table(["Metric", "Value"], rows)

    def _section_strength(self, hevy: dict) -> str:
        lines = [_h(2, "Strength Training (Hevy)"), ""]

        lines.append(f"**Workouts completed:** {hevy.get('workout_count', 0)}")
        lines.append(f"**Workouts per week:** {hevy.get('workouts_per_week', 0.0)}")
        dates = hevy.get("workout_dates", [])
        if dates:
            lines.append(f"**Training dates:** {', '.join(dates)}")
        lines.append("")

        vol = hevy.get("volume_by_muscle_group", {})
        if vol:
            lines.append(_h(3, "Volume by Muscle Group"))
            lines.append(_table(
                ["Muscle Group", "Total Volume (kg×reps)"],
                [[k, v] for k, v in vol.items()]
            ))
            lines.append("")

        prs = hevy.get("personal_records", [])
        if prs:
            lines.append(_h(3, "Personal Records This Period"))
            lines.append(_table(
                ["Exercise", "Weight (kg)", "Reps"],
                [[pr["exercise"], pr["weight_kg"], pr["reps"]] for pr in prs]
            ))
            lines.append("")

        exercises = hevy.get("exercises", {})
        if exercises:
            lines.append(_h(3, "Exercise Breakdown"))
            lines.append(_table(
                ["Exercise", "Muscle Group", "Sets", "Reps", "Max Weight (kg)"],
                [[name, ex["muscle_group"], ex["total_sets"], ex["total_reps"], ex["max_weight_kg"]]
                 for name, ex in exercises.items()]
            ))

        return "\n".join(lines)

    def _section_runs(self, runs: dict) -> str:
        lines = [_h(2, "Running (Garmin)"), ""]
        if not runs.get("run_count"):
            lines.append("_No runs recorded this period._")
            return "\n".join(lines)

        summary = [
            ["Runs completed", str(runs["run_count"])],
            ["Total distance", _fmt(runs.get("total_distance_km"), "km")],
            ["Average pace", _fmt_pace(runs.get("avg_pace_min_km"))],
        ]
        lines.append(_table(["Metric", "Value"], summary))
        lines.append("")

        individual = runs.get("runs", [])
        if individual:
            lines.append(_h(3, "Individual Runs"))
            lines.append(_table(
                ["Date", "Distance (km)", "Duration (min)", "Avg Pace (min/km)", "Avg HR"],
                [
                    [r["date"], r["distance_km"], r["duration_min"],
                     _fmt_pace(r.get("avg_pace_min_km")), r.get("avg_hr") or "—"]
                    for r in individual
                ]
            ))
        return "\n".join(lines)

    def _section_training_load(self, load: dict) -> str:
        lines = [_h(2, "Training Load"), ""]
        lines.append(f"**Average training load:** {_fmt(load.get('avg_load'), '')}")
        lines.append(f"**Latest training status:** {load.get('latest_status') or '—'}")
        lines.append("")

        daily = load.get("daily", [])
        if daily:
            lines.append(_table(
                ["Date", "Training Load", "Status"],
                [[d["date"], d.get("training_load", "—"), d.get("status", "—")] for d in daily]
            ))
        return "\n".join(lines)


def _fmt(value, unit: str) -> str:
    if value is None:
        return "—"
    return f"{value} {unit}".strip()


def _fmt_pace(value) -> str:
    """Format a decimal minutes-per-km value as M:SS."""
    if value is None:
        return "—"
    mins = int(value)
    secs = round((value - mins) * 60)
    return f"{mins}:{secs:02d} min/km"
