"""Markdown report generator for AIFitnessSummary.

Generates structured reports aligned with the proposal:
- Weekly Digest: Sleep, Strength, Running, Recovery, Nutrition + AI narrative
- Block Check-In: Adaptation assessment + programme recommendations
- End-of-Programme: Goal achievement + next block planning

Reports are written as Markdown files and can be converted to HTML for email.
"""

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


def _fmt(value, unit: str = "") -> str:
    if value is None:
        return "---"
    return f"{value} {unit}".strip()


class ReportGenerator:
    """Assembles aggregated metrics and AI narrative into a Markdown report."""

    def generate(
        self,
        cadence: str,
        start_date: datetime.date,
        end_date: datetime.date,
        summary: dict,
        claude_narrative: str,
        plan_context: str = "",
        escalation_flags: list[dict] | None = None,
    ) -> Path:
        REPORT_DIR.mkdir(exist_ok=True)
        filename = f"{cadence}_review_{end_date.strftime(DATE_FORMAT)}.md"
        output_path = REPORT_DIR / filename

        sections = self._build_sections(
            cadence, start_date, end_date, summary,
            claude_narrative, plan_context, escalation_flags,
        )
        output_path.write_text("\n\n".join(sections), encoding="utf-8")
        return output_path

    def _build_sections(
        self,
        cadence: str,
        start: datetime.date,
        end: datetime.date,
        summary: dict,
        narrative: str,
        plan_context: str,
        escalation_flags: list[dict] | None,
    ) -> list[str]:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

        cadence_label = {
            "weekly": "Weekly Digest",
            "block_checkin": "Block Check-In",
            "end_of_programme": "End-of-Programme Review",
        }.get(cadence, cadence.replace("_", " ").title())

        header = "\n".join([
            f"# {cadence_label} --- {end.strftime('%B %d, %Y')}",
            "",
            f"**Period:** {start.strftime(DATE_FORMAT)} to {end.strftime(DATE_FORMAT)}  ",
            f"**Generated:** {now}  ",
            f"**Sources:** Garmin Connect, Hevy App, Claude (`{__import__('config').MODEL}`)  ",
        ])

        sections = [header]

        # AI Narrative (the main content)
        sections.append(narrative)

        # Escalation flags
        if escalation_flags:
            sections.append(self._section_escalation_flags(escalation_flags))

        # Data tables by domain
        sections.append(self._section_sleep(summary))
        sections.append(self._section_strength(summary))
        sections.append(self._section_running(summary))
        sections.append(self._section_recovery(summary))
        sections.append(self._section_nutrition(summary))

        # Block-level additions
        if cadence in ("block_checkin", "end_of_programme"):
            block_section = self._section_block_metrics(summary)
            if block_section:
                sections.append(block_section)

        return sections

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _section_escalation_flags(self, flags: list[dict]) -> str:
        lines = [_h(2, "Escalation Flags"), ""]
        for flag in flags:
            severity_icon = "!!!" if flag.get("severity") == "warning" else ">"
            lines.append(f"- **{flag['condition']}** {severity_icon} {flag['advisory']}")
        return "\n".join(lines)

    def _section_sleep(self, summary: dict) -> str:
        rows = [
            ["Average sleep duration", _fmt(summary.get("sleep_avg_duration_h"), "hours")],
            ["Bedtime consistency (SD)", _fmt(summary.get("sleep_bedtime_consistency_sd_min"), "min")],
            ["Sleep efficiency", _fmt(summary.get("sleep_efficiency_pct"), "%")],
            ["Sleep respiratory rate", _fmt(summary.get("sleep_respiration_brpm"), "brpm")],
            ["Overnight resting HR", _fmt(summary.get("overnight_rhr_avg_bpm"), "bpm")],
            ["Nights tracked", _fmt(summary.get("sleep_nights_tracked"))],
        ]
        return _h(2, "Sleep") + "\n\n" + _table(["Metric", "Value"], rows)

    def _section_strength(self, summary: dict) -> str:
        lines = [_h(2, "Strength Training"), ""]

        completed = summary.get("strength_sessions_completed", 0)
        planned = summary.get("strength_sessions_planned")
        adherence = summary.get("strength_session_adherence_pct")
        if planned:
            lines.append(f"**Sessions:** {completed} / {planned} planned ({adherence}%)")
        else:
            lines.append(f"**Sessions:** {completed}")
        lines.append("")

        # Sets per muscle group vs targets
        sets_per_group = summary.get("sets_per_muscle_group", {})
        volume_targets = summary.get("volume_targets", {})
        if sets_per_group:
            lines.append(_h(3, "Sets per Muscle Group"))
            rows = []
            for group, sets in sets_per_group.items():
                target = volume_targets.get(group, {})
                if target:
                    target_range = f"{target.get('min')}-{target.get('max')}"
                    status = "On target"
                    if sets < target.get("min", 0):
                        status = "Below target"
                    elif sets > target.get("max", 999):
                        status = "Above target"
                    rows.append([group, str(sets), target_range, status])
                else:
                    rows.append([group, str(sets), "---", "---"])
            lines.append(_table(["Muscle Group", "Sets", "Target Range", "Status"], rows))
            lines.append("")

        # Primary lift top sets
        top_sets = summary.get("primary_lift_top_sets", {})
        if top_sets:
            lines.append(_h(3, "Primary Compound Lifts"))
            rows = [
                [lift, f"{d['weight_kg']}kg", str(d["reps"]), f"{d['estimated_1rm']}kg"]
                for lift, d in top_sets.items()
            ]
            lines.append(_table(["Lift", "Top Set", "Reps", "Est. 1RM"], rows))

        return "\n".join(lines)

    def _section_running(self, summary: dict) -> str:
        lines = [_h(2, "Running"), ""]

        total_km = summary.get("running_total_km", 0)
        planned_km = summary.get("running_planned_km")
        compliance = summary.get("running_volume_compliance_pct")

        rows = [
            ["Total volume", _fmt(total_km, "km") + (f" / {planned_km} km planned" if planned_km else "")],
            ["Volume compliance", _fmt(compliance, "%") if compliance else "---"],
            ["Easy km / Hard km", f"{summary.get('running_easy_km', 0)} / {summary.get('running_hard_km', 0)}"],
            ["Intensity distribution", f"{_fmt(summary.get('running_easy_pct'), '%')} easy / {_fmt(summary.get('running_hard_pct'), '%')} hard"],
            ["Runs completed", str(summary.get("run_count", 0)) + (f" / {summary.get('runs_planned')} planned" if summary.get('runs_planned') else "")],
        ]
        lines.append(_table(["Metric", "Value"], rows))
        return "\n".join(lines)

    def _section_recovery(self, summary: dict) -> str:
        rows = [
            ["7-day avg resting HR", _fmt(summary.get("resting_hr_avg_bpm"), "bpm")],
            ["HRV 7-day status", _fmt(summary.get("hrv_status_label"))],
        ]
        return _h(2, "Recovery") + "\n\n" + _table(["Metric", "Value"], rows)

    def _section_nutrition(self, summary: dict) -> str:
        rows = [
            ["Avg daily protein", _fmt(summary.get("nutrition_avg_protein_g"), "g")],
            ["Avg daily calories", _fmt(summary.get("nutrition_avg_calories"), "kcal")],
            ["7-day avg bodyweight", _fmt(summary.get("bodyweight_avg_kg"), "kg")],
            ["Latest bodyweight", _fmt(summary.get("bodyweight_latest_kg"), "kg")],
        ]
        return _h(2, "Nutrition") + "\n\n" + _table(["Metric", "Value"], rows)

    def _section_block_metrics(self, summary: dict) -> str | None:
        training_status = summary.get("training_status_label")
        vo2max = summary.get("vo2max_estimate")
        if not training_status and not vo2max:
            return None
        rows = [
            ["Training Status", _fmt(training_status)],
            ["VO2max estimate", _fmt(vo2max, "ml/kg/min")],
        ]
        return _h(2, "Block-Level Metrics") + "\n\n" + _table(["Metric", "Value"], rows)
