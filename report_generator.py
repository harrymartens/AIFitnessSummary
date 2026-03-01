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
    ) -> Path:
        REPORT_DIR.mkdir(exist_ok=True)
        filename = f"{period}_review_{end_date.strftime(DATE_FORMAT)}.md"
        output_path = REPORT_DIR / filename

        sections = self._build_sections(
            period, start_date, end_date, garmin_data, hevy_summary, claude_narrative
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

        # Activity Overview (raw data table)
        sections.append(self._section_activity(garmin["stats"]))

        # Cardiovascular Health
        sections.append(self._section_cardio(garmin["heart_rate"], garmin["hrv"]))

        # Sleep Analysis
        sections.append(self._section_sleep(garmin["sleep"]))

        # Recovery & Stress
        sections.append(self._section_recovery(garmin["stress"], garmin["body_battery"]))

        # Strength Training (Hevy)
        sections.append(self._section_strength(hevy))

        # Training Load
        sections.append(self._section_training_load(garmin["training_load"]))

        # Claude's full narrative (minus the Executive Summary which is shown first)
        insights_key = "Recommendations for Next Period"
        insights = narrative_sections.get(insights_key, "")
        remaining = self._narrative_minus_exec(narrative)
        sections.append(_h(2, "Claude's Insights & Recommendations") + "\n\n" + remaining)

        return sections

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
            ["Average active minutes/day", _fmt(stats.get("avg_active_minutes"), "min")],
            ["Average intensity minutes/day", _fmt(stats.get("avg_intensity_minutes"), "min")],
            ["Days with data", str(stats.get("days_with_data", "—"))],
        ]
        return _h(2, "Activity Overview") + "\n\n" + _table(["Metric", "Value"], rows)

    def _section_cardio(self, hr: dict, hrv: dict) -> str:
        lines = [_h(2, "Cardiovascular Health"), ""]

        # Resting HR summary
        lines.append(f"**Average resting heart rate:** {_fmt(hr.get('avg_resting_hr'), 'bpm')}")
        lines.append(f"**Period HRV average:** {_fmt(hrv.get('period_avg_ms'), 'ms')}")
        lines.append("")

        # HR trend table
        trend = hr.get("daily_trend", [])
        if trend:
            lines.append(_h(3, "Resting HR Daily Trend"))
            lines.append(_table(
                ["Date", "Resting HR (bpm)"],
                [[e["date"], e["resting_hr"]] for e in trend]
            ))
            lines.append("")

        # HRV table
        hrv_daily = hrv.get("daily", [])
        if hrv_daily:
            lines.append(_h(3, "HRV Daily Status"))
            lines.append(_table(
                ["Date", "Status", "Last Night Avg (ms)"],
                [[e["date"], e.get("status", "—"), e.get("last_night_avg_ms", "—")] for e in hrv_daily]
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
        ]
        lines.append(_table(["Metric", "Average"], averages))
        lines.append("")

        nightly = sleep.get("nightly", [])
        if nightly:
            lines.append(_h(3, "Nightly Breakdown"))
            lines.append(_table(
                ["Date", "Total (h)", "Deep (h)", "REM (h)", "Light (h)", "Awake (h)"],
                [[n["date"], n["total_h"], n["deep_h"], n["rem_h"], n["light_h"], n["awake_h"]]
                 for n in nightly]
            ))
        return "\n".join(lines)

    def _section_recovery(self, stress: dict, battery: dict) -> str:
        lines = [_h(2, "Recovery & Stress"), ""]
        summary = [
            ["Average stress level", _fmt(stress.get("avg_stress"), "/100")],
            ["Avg body battery charged", _fmt(battery.get("avg_max"), "pts")],
            ["Avg body battery drained", _fmt(battery.get("avg_min"), "pts")],
        ]
        lines.append(_table(["Metric", "Value"], summary))
        lines.append("")

        daily = stress.get("daily", [])
        if daily:
            lines.append(_h(3, "Daily Stress Levels"))
            lines.append(_table(
                ["Date", "Avg Stress"],
                [[d["date"], d["avg_stress"]] for d in daily]
            ))
        return "\n".join(lines)

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
