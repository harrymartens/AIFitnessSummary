"""Data aggregation layer for AIFitnessSummary.

Transforms raw data from Garmin, Hevy, and Nutrition clients into
the summary statistics defined in the proposal (Section 7).

All raw data is processed to summary statistics before being passed
to the AI. The AI never receives raw event-level data.

Also implements the escalation flag system (Section 6.2).
"""

from typing import Optional


def aggregate_weekly(
    garmin_data: dict,
    hevy_summary: dict,
    nutrition_data: dict | None,
    plan_context: dict | None = None,
) -> dict:
    """Aggregate all data sources into a weekly digest summary.

    Returns a flat dict of summary statistics by domain, ready for
    injection into the AI prompt.
    """
    sleep = garmin_data.get("sleep", {})
    resting_hr = garmin_data.get("resting_hr", {})
    respiration = garmin_data.get("sleep_respiration", {})
    hrv = garmin_data.get("hrv", {})
    runs = garmin_data.get("runs", {})
    body_comp = garmin_data.get("body_composition", {})

    # Nutrition (may come from nutrition_client or be None)
    weight_data = {}
    nutri_data = {}
    if nutrition_data:
        weight_data = nutrition_data.get("weight", {})
        nutri_data = nutrition_data.get("nutrition", {})

    # Merge weight: prefer nutrition_client (scale data) over Garmin
    merged_weight = weight_data.get("avg_weight_kg") or body_comp.get("avg_weight_kg")
    latest_weight = weight_data.get("latest_weight_kg") or body_comp.get("latest_weight_kg")

    # Plan targets
    plan = plan_context or {}
    volume_targets = plan.get("volume_targets", {})
    planned_km = plan.get("planned_weekly_km")
    planned_sessions = plan.get("planned_sessions")
    planned_runs = plan.get("planned_runs")

    return {
        # Sleep (Section 4.1)
        "sleep_avg_duration_h": sleep.get("avg_total_h"),
        "sleep_bedtime_consistency_sd_min": sleep.get("bedtime_consistency_sd_min"),
        "sleep_efficiency_pct": sleep.get("avg_sleep_efficiency_pct"),
        "sleep_respiration_brpm": respiration.get("avg_sleep_respiration_brpm"),
        "sleep_nights_tracked": sleep.get("nights_tracked"),

        # Recovery (Section 4.4)
        "resting_hr_avg_bpm": resting_hr.get("avg_resting_hr"),
        "hrv_status_label": hrv.get("hrv_status_label"),

        # Strength (Section 4.2)
        "strength_sessions_completed": hevy_summary.get("workout_count", 0),
        "strength_sessions_planned": planned_sessions,
        "strength_session_adherence_pct": _adherence_pct(
            hevy_summary.get("workout_count", 0), planned_sessions
        ),
        "sets_per_muscle_group": hevy_summary.get("sets_per_muscle_group", {}),
        "volume_load_per_muscle_group": hevy_summary.get("volume_load_per_muscle_group", {}),
        "volume_targets": volume_targets,
        "primary_lift_top_sets": hevy_summary.get("primary_lift_top_sets", {}),

        # Running (Section 4.3)
        "running_total_km": runs.get("total_distance_km", 0.0),
        "running_planned_km": planned_km,
        "running_volume_compliance_pct": _adherence_pct(
            runs.get("total_distance_km", 0.0), planned_km
        ),
        "running_easy_pct": runs.get("easy_pct"),
        "running_hard_pct": runs.get("hard_pct"),
        "running_easy_km": runs.get("easy_km", 0.0),
        "running_hard_km": runs.get("hard_km", 0.0),
        "run_count": runs.get("run_count", 0),
        "runs_planned": planned_runs,

        # Nutrition (Section 4.5)
        "nutrition_avg_protein_g": nutri_data.get("avg_daily_protein_g"),
        "nutrition_avg_calories": nutri_data.get("avg_daily_calories"),
        "bodyweight_avg_kg": merged_weight,
        "bodyweight_latest_kg": latest_weight,

        # Overnight RHR (part of sleep recovery per Section 4.1)
        "overnight_rhr_avg_bpm": resting_hr.get("avg_resting_hr"),
    }


def detect_escalation_flags(
    summary: dict,
    bodyweight_kg: float | None = None,
) -> list[dict]:
    """Check aggregated data for escalation conditions (Section 6.2).

    Returns a list of advisory dicts: {condition, advisory, severity}.
    """
    flags = []

    # Bedtime consistency SD > 45 minutes
    bedtime_sd = summary.get("sleep_bedtime_consistency_sd_min")
    if bedtime_sd is not None and bedtime_sd > 45:
        flags.append({
            "condition": f"Bedtime consistency SD: {bedtime_sd:.0f} min (>45 min threshold)",
            "advisory": "Circadian disruption flag; sleep consistency is a high-yield intervention",
            "severity": "warning",
        })

    # Muscle group volume flags — use plan targets if available, otherwise 10/20 defaults
    sets_per_group = summary.get("sets_per_muscle_group", {})
    volume_targets = summary.get("volume_targets", {})
    for group, sets in sets_per_group.items():
        target = volume_targets.get(group, {})
        min_threshold = target.get("min", 10)
        if sets < min_threshold:
            flags.append({
                "condition": f"{group}: {sets} sets/week (<{min_threshold} threshold)",
                "advisory": f"Under-stimulation flag for {group}",
                "severity": "warning",
            })

    for group, sets in sets_per_group.items():
        target = volume_targets.get(group, {})
        max_threshold = target.get("max", 20)
        if sets > max_threshold:
            flags.append({
                "condition": f"{group}: {sets} sets/week (>{max_threshold} threshold)",
                "advisory": f"Diminishing returns threshold exceeded for {group}; recovery risk",
                "severity": "warning",
            })

    # Hard running > 20% of weekly km
    hard_pct = summary.get("running_hard_pct")
    if hard_pct is not None and hard_pct > 20:
        flags.append({
            "condition": f"Hard running: {hard_pct:.1f}% of weekly km (>20% threshold)",
            "advisory": "Concurrent interference risk; redistribute intensity",
            "severity": "warning",
        })

    # Protein below 1.6 g/kg
    protein_g = summary.get("nutrition_avg_protein_g")
    bw = bodyweight_kg or summary.get("bodyweight_avg_kg")
    if protein_g is not None and bw is not None and bw > 0:
        protein_per_kg = protein_g / bw
        if protein_per_kg < 1.6:
            flags.append({
                "condition": f"Protein: {protein_g:.0f}g/day ({protein_per_kg:.1f}g/kg, <1.6g/kg threshold)",
                "advisory": "Muscle protein synthesis substrate insufficient",
                "severity": "warning",
            })

    # Session adherence < 80%
    adherence = summary.get("strength_session_adherence_pct")
    if adherence is not None and adherence < 80:
        flags.append({
            "condition": f"Session adherence: {adherence:.0f}% (<80% threshold)",
            "advisory": "Adherence is the primary adaptation driver; investigate cause",
            "severity": "warning",
        })

    # Sleep efficiency < 85%
    efficiency = summary.get("sleep_efficiency_pct")
    if efficiency is not None and efficiency < 85:
        flags.append({
            "condition": f"Sleep efficiency: {efficiency:.1f}% (<85% threshold)",
            "advisory": "Fragmented sleep detected",
            "severity": "info",
        })

    return flags


def aggregate_block_checkin(
    garmin_data: dict,
    hevy_summary: dict,
    nutrition_data: dict | None,
    plan_context: dict | None = None,
) -> dict:
    """Aggregate data for a block check-in (deload week).

    Adds block-level metrics on top of the weekly summary:
    - Training Status label
    - VO2max direction
    - Estimated 1RM on primary lifts
    """
    weekly = aggregate_weekly(garmin_data, hevy_summary, nutrition_data, plan_context)

    # Block-only additions
    training_status = garmin_data.get("training_status", {})
    vo2max = garmin_data.get("vo2max", {})

    weekly.update({
        "training_status_label": training_status.get("training_status"),
        "vo2max_estimate": vo2max.get("vo2_max"),
    })

    return weekly


def _adherence_pct(actual, planned) -> Optional[float]:
    """Calculate adherence percentage, or None if no plan target."""
    if planned is None or planned == 0:
        return None
    return round((actual / planned) * 100, 1)
