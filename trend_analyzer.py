"""
trend_analyzer.py

Persists review snapshots to SQLite and retrieves historical trend context
for injection into Claude prompts and report generation.
"""

from __future__ import annotations

from typing import Optional

from db_client import DatabaseClient

_trend_analyzer_singleton: Optional["TrendAnalyzer"] = None


class TrendAnalyzer:
    """Saves review snapshots and retrieves formatted historical trend context."""

    def __init__(self, db: DatabaseClient) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save_review(
        self,
        period: str,
        start_date,
        end_date,
        garmin_data: dict,
        hevy_data: dict,
        report_path: str = None,
    ) -> int:
        """Extract key metrics from garmin_data and hevy_data and save to DB.

        Returns the new review_id.

        Key metrics extracted:
        - avg_steps: garmin_data.get("steps", {}).get("avg_daily_steps")
        - avg_sleep_hours: garmin_data.get("sleep", {}).get("avg_total_sleep")
        - avg_resting_hr: garmin_data.get("heart_rate", {}).get("avg_resting_hr")
        - avg_hrv: garmin_data.get("hrv", {}).get("avg_hrv")
        - avg_stress: garmin_data.get("stress", {}).get("avg_stress")
        - avg_body_battery: garmin_data.get("body_battery", {}).get("avg_charged")
        - avg_spo2: garmin_data.get("spo2", {}).get("avg_spo2")
        - avg_vo2max: garmin_data.get("vo2max", {}).get("vo2max")
        - avg_weight_kg: garmin_data.get("body_composition", {}).get("avg_weight")
        - avg_body_fat_pct: garmin_data.get("body_composition", {}).get("avg_body_fat")
        - workouts_count: hevy_data.get("total_workouts")
        - total_volume_kg: hevy_data.get("total_volume_kg") or sum of volume_by_muscle.values()
        - total_run_distance_km: garmin_data.get("running", {}).get("total_distance_km")

        Also saves daily step counts to metrics_history if available:
        garmin_data.get("steps", {}).get("daily_steps", []) — list of {"date": str, "steps": int}
        """
        # Normalise date arguments to ISO strings
        start_str = start_date if isinstance(start_date, str) else start_date.isoformat()
        end_str = end_date if isinstance(end_date, str) else end_date.isoformat()

        # --- Extract metrics ---
        steps_data = garmin_data.get("steps", {}) or {}
        sleep_data = garmin_data.get("sleep", {}) or {}
        hr_data = garmin_data.get("heart_rate", {}) or {}
        hrv_data = garmin_data.get("hrv", {}) or {}
        stress_data = garmin_data.get("stress", {}) or {}
        bb_data = garmin_data.get("body_battery", {}) or {}
        spo2_data = garmin_data.get("spo2", {}) or {}
        vo2max_data = garmin_data.get("vo2max", {}) or {}
        body_comp_data = garmin_data.get("body_composition", {}) or {}
        running_data = garmin_data.get("running", {}) or {}

        # Total volume: prefer explicit key, fall back to summing volume_by_muscle
        total_volume_kg = hevy_data.get("total_volume_kg")
        if total_volume_kg is None:
            volume_by_muscle = hevy_data.get("volume_by_muscle") or {}
            if volume_by_muscle:
                total_volume_kg = sum(volume_by_muscle.values())

        review = {
            "period": period,
            "start_date": start_str,
            "end_date": end_str,
            "report_path": report_path,
            "avg_steps": steps_data.get("avg_daily_steps"),
            "avg_sleep_hours": sleep_data.get("avg_total_sleep"),
            "avg_resting_hr": hr_data.get("avg_resting_hr"),
            "avg_hrv": hrv_data.get("avg_hrv"),
            "avg_stress": stress_data.get("avg_stress"),
            "avg_body_battery": bb_data.get("avg_charged"),
            "avg_spo2": spo2_data.get("avg_spo2"),
            "avg_vo2max": vo2max_data.get("vo2max"),
            "avg_weight_kg": body_comp_data.get("avg_weight"),
            "avg_body_fat_pct": body_comp_data.get("avg_body_fat"),
            "workouts_count": hevy_data.get("total_workouts"),
            "total_volume_kg": total_volume_kg,
            "total_run_distance_km": running_data.get("total_distance_km"),
        }

        review_id = self._db.save_review(review)

        # --- Save daily steps to metrics_history ---
        daily_steps = steps_data.get("daily_steps", []) or []
        if daily_steps:
            daily_metrics = [
                {
                    "date": entry["date"],
                    "metric_name": "steps",
                    "metric_value": entry.get("steps"),
                }
                for entry in daily_steps
                if entry.get("date") is not None
            ]
            if daily_metrics:
                self._db.save_metrics_history(review_id, daily_metrics)

        return review_id

    def get_trend_context(self, n: int = 6, current_period: str = None) -> str:
        """Retrieve the last n completed reviews formatted as a [HISTORICAL CONTEXT] block.

        Returns empty string if fewer than 2 reviews exist (no trend to show).

        Example output:

        [HISTORICAL CONTEXT — LAST 4 REVIEWS]

        Date Range          | Period  | Steps  | Sleep  | Resting HR | HRV  | Weight | Workouts | Volume
        2026-01-05→01-11    | weekly  | 8,234  | 7.1h   | 58         | 52   | 87.2kg | 4        | 8,450kg
        ...

        Trends (oldest→newest):
        - Steps: ↑ improving (+522 avg/day)
        ...
        """
        reviews = self._db.get_recent_reviews(n)
        # get_recent_reviews returns newest first — reverse to get oldest first
        reviews = list(reversed(reviews))

        if len(reviews) < 2:
            return ""

        count = len(reviews)
        lines: list[str] = []

        lines.append(f"[HISTORICAL CONTEXT — LAST {count} REVIEWS]")
        lines.append("")

        # Header row
        header = (
            f"{'Date Range':<20}| {'Period':<8}| {'Steps':<7}| {'Sleep':<7}| "
            f"{'Resting HR':<11}| {'HRV':<5}| {'Weight':<7}| {'Workouts':<9}| Volume"
        )
        lines.append(header)

        # Data rows
        for r in reviews:
            date_range = self._fmt_date_range(r["start_date"], r["end_date"])
            period = r.get("period") or "—"
            steps = self._fmt_val(r.get("avg_steps"), decimals=0, suffix="")
            if steps != "—":
                try:
                    steps = f"{int(float(steps)):,}"
                except (ValueError, TypeError):
                    pass
            sleep = self._fmt_val(r.get("avg_sleep_hours"), decimals=1, suffix="h")
            resting_hr = self._fmt_val(r.get("avg_resting_hr"), decimals=0)
            hrv = self._fmt_val(r.get("avg_hrv"), decimals=0)
            weight = self._fmt_val(r.get("avg_weight_kg"), decimals=1, suffix="kg")
            workouts = self._fmt_val(r.get("workouts_count"), decimals=0)
            volume_raw = r.get("total_volume_kg")
            if volume_raw is not None:
                try:
                    volume = f"{int(float(volume_raw)):,}kg"
                except (ValueError, TypeError):
                    volume = "—"
            else:
                volume = "—"

            row = (
                f"{date_range:<20}| {period:<8}| {steps:<7}| {sleep:<7}| "
                f"{resting_hr:<11}| {hrv:<5}| {weight:<7}| {workouts:<9}| {volume}"
            )
            lines.append(row)

        lines.append("")
        lines.append("Trends (oldest→newest):")

        # Collect values for trend computation (oldest→newest already)
        steps_vals = self._extract_vals(reviews, "avg_steps")
        sleep_vals = self._extract_vals(reviews, "avg_sleep_hours")
        rhr_vals = self._extract_vals(reviews, "avg_resting_hr")
        hrv_vals = self._extract_vals(reviews, "avg_hrv")
        weight_vals = self._extract_vals(reviews, "avg_weight_kg")
        volume_vals = self._extract_vals(reviews, "total_volume_kg")

        # Steps
        if len(steps_vals) >= 2:
            label = self._compute_trend_label(steps_vals, higher_is_better=True)
            delta = steps_vals[-1] - steps_vals[0]
            sign = "+" if delta >= 0 else ""
            lines.append(f"- Steps: {label} ({sign}{delta:.0f} avg/day)")

        # Sleep
        if len(sleep_vals) >= 2:
            label = self._compute_trend_label(sleep_vals, higher_is_better=True)
            delta = sleep_vals[-1] - sleep_vals[0]
            sign = "+" if delta >= 0 else ""
            lines.append(f"- Sleep: {label} ({sign}{delta:.1f}h avg)")

        # Resting HR (lower is better)
        if len(rhr_vals) >= 2:
            label = self._compute_trend_label(rhr_vals, higher_is_better=False)
            delta = rhr_vals[-1] - rhr_vals[0]
            sign = "+" if delta >= 0 else ""
            lines.append(f"- Resting HR: {label} ({sign}{delta:.0f} bpm)")

        # HRV
        if len(hrv_vals) >= 2:
            label = self._compute_trend_label(hrv_vals, higher_is_better=True)
            delta = hrv_vals[-1] - hrv_vals[0]
            sign = "+" if delta >= 0 else ""
            lines.append(f"- HRV: {label} ({sign}{delta:.0f} ms)")

        # Weight (neutral — just show delta)
        if len(weight_vals) >= 2:
            delta = weight_vals[-1] - weight_vals[0]
            sign = "+" if delta >= 0 else ""
            direction = "▲" if delta > 0 else ("▼" if delta < 0 else "→")
            lines.append(f"- Weight: {direction} {sign}{delta:.1f} kg over period")

        # Training volume
        if len(volume_vals) >= 2:
            label = self._compute_trend_label(volume_vals, higher_is_better=True)
            delta = volume_vals[-1] - volume_vals[0]
            sign = "+" if delta >= 0 else ""
            lines.append(f"- Training Volume: {label} ({sign}{delta:,.0f} kg)")

        return "\n".join(lines)

    def _compute_trend_label(self, values: list[float], higher_is_better: bool = True) -> str:
        """Given a list of values (oldest first), return a trend label.

        Compares first-half average to second-half average.
        A change of less than 5% is considered stable.

        Returns: "↑ improving", "↓ declining", or "→ stable"
        """
        if len(values) < 2:
            return "→ stable"

        mid = len(values) // 2
        first_half = values[:mid] if mid > 0 else values[:1]
        second_half = values[mid:] if mid < len(values) else values[-1:]

        first_avg = sum(first_half) / len(first_half)
        second_avg = sum(second_half) / len(second_half)

        if first_avg == 0:
            # Avoid division by zero; treat any change as non-stable
            pct_change = abs(second_avg - first_avg)
            if pct_change < 0.05:
                return "→ stable"
        else:
            pct_change = abs(second_avg - first_avg) / abs(first_avg)

        STABLE_THRESHOLD = 0.05

        if pct_change < STABLE_THRESHOLD:
            return "→ stable"

        improved = second_avg > first_avg
        if not higher_is_better:
            improved = not improved

        return "↑ improving" if improved else "↓ declining"

    def _fmt_val(self, val, decimals: int = 0, suffix: str = "") -> str:
        """Format a numeric value, or return '—' if None."""
        if val is None:
            return "—"
        try:
            formatted = f"{float(val):.{decimals}f}"
            return f"{formatted}{suffix}"
        except (ValueError, TypeError):
            return "—"

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fmt_date_range(start_date: str, end_date: str) -> str:
        """Format 'YYYY-MM-DD' pair as 'YYYY-MM-DD→MM-DD'."""
        try:
            start_short = start_date  # e.g. "2026-01-05"
            # Show end as MM-DD only
            end_parts = end_date.split("-")
            end_short = f"{end_parts[1]}-{end_parts[2]}" if len(end_parts) == 3 else end_date
            return f"{start_short}→{end_short}"
        except Exception:
            return f"{start_date}→{end_date}"

    @staticmethod
    def _extract_vals(reviews: list[dict], key: str) -> list[float]:
        """Extract non-None float values for a given key from a list of review dicts."""
        result = []
        for r in reviews:
            v = r.get(key)
            if v is not None:
                try:
                    result.append(float(v))
                except (ValueError, TypeError):
                    pass
        return result


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


def get_trend_analyzer() -> TrendAnalyzer:
    """Return the TrendAnalyzer singleton using the module-level db."""
    global _trend_analyzer_singleton
    if _trend_analyzer_singleton is None:
        from db_client import get_db

        _trend_analyzer_singleton = TrendAnalyzer(get_db())
    return _trend_analyzer_singleton
