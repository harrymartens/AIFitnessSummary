"""
knowledge_client.py

Provides evidence-based fitness knowledge to inject into Claude prompts.
Stage 4A: Curated knowledge base selection and summarisation.
Stage 4B (separate): PubMed + examine.com live search and caching.
"""

from pathlib import Path

KNOWLEDGE_BASE_DIR = Path(__file__).parent / "knowledge_base"

TOPIC_FILES = {
    "strength_training": "strength_training.md",
    "sleep": "sleep_science.md",
    "hrv": "hrv_interpretation.md",
    "cardiovascular": "cardiovascular.md",
    "recovery": "recovery.md",
}

# Human-readable labels for each topic key (used in formatted output headers)
TOPIC_LABELS = {
    "strength_training": "STRENGTH TRAINING",
    "sleep": "SLEEP SCIENCE",
    "hrv": "HRV INTERPRETATION",
    "cardiovascular": "CARDIOVASCULAR FITNESS",
    "recovery": "RECOVERY",
}


def select_relevant_topics(metrics: dict) -> list[str]:
    """
    Given the current metrics dict, return up to 2 topic keys most relevant
    to surface in this review. Heuristic rules:

    - HRV below 50 or declining → "hrv", "recovery"
    - Sleep < 6.5 hrs avg OR deep sleep < 15% → "sleep"
    - workouts_count >= 3 → "strength_training"
    - VO2max present OR runs exist → "cardiovascular"
    - stress > 60 OR body_battery_avg < 40 → "recovery"
    - Default fallback: ["strength_training", "sleep"]

    Returns at most 2 topics.
    """
    selected: list[str] = []

    # Extract sub-dicts; metrics may be a combined dict (garmin + hevy keys)
    # or a garmin_data dict with nested structure.
    hrv_data = metrics.get("hrv", {})
    sleep_data = metrics.get("sleep", {})
    stress_data = metrics.get("stress", {})
    body_battery_data = metrics.get("body_battery", {})
    vo2_data = metrics.get("vo2max", {})
    runs_data = metrics.get("runs", {})

    # HRV signals — check period average and whether daily values show a
    # declining trend (last reading below 7-day average).
    hrv_avg = hrv_data.get("period_avg_ms")
    hrv_low = hrv_avg is not None and hrv_avg < 50

    hrv_declining = False
    daily_hrv = hrv_data.get("daily", [])
    if len(daily_hrv) >= 3:
        recent_values = [
            d.get("last_night_avg_ms")
            for d in daily_hrv[-3:]
            if d.get("last_night_avg_ms") is not None
        ]
        older_values = [
            d.get("last_night_avg_ms")
            for d in daily_hrv[:-3]
            if d.get("last_night_avg_ms") is not None
        ]
        if recent_values and older_values:
            hrv_declining = (
                sum(recent_values) / len(recent_values)
                < sum(older_values) / len(older_values)
            )

    if hrv_low or hrv_declining:
        _add_topics(selected, ["hrv", "recovery"])

    # Sleep signals — average total hours and deep-sleep percentage.
    if len(selected) < 2:
        avg_total_h = sleep_data.get("avg_total_h")
        avg_deep_h = sleep_data.get("avg_deep_h")

        sleep_short = avg_total_h is not None and avg_total_h < 6.5
        deep_pct_low = (
            avg_total_h is not None
            and avg_deep_h is not None
            and avg_total_h > 0
            and (avg_deep_h / avg_total_h) < 0.15
        )

        if sleep_short or deep_pct_low:
            _add_topics(selected, ["sleep"])

    # Stress / body battery signals — check for high chronic stress or low
    # body battery reserve.
    if len(selected) < 2:
        avg_stress = stress_data.get("avg_stress")
        body_battery_avg = body_battery_data.get("avg_max")  # daily max = charged level

        high_stress = avg_stress is not None and avg_stress > 60
        low_battery = body_battery_avg is not None and body_battery_avg < 40

        if high_stress or low_battery:
            _add_topics(selected, ["recovery"])

    # Cardiovascular signals — VO2 max recorded or running activity present.
    if len(selected) < 2:
        has_vo2 = vo2_data.get("vo2_max") is not None
        has_runs = runs_data.get("run_count", 0) > 0

        if has_vo2 or has_runs:
            _add_topics(selected, ["cardiovascular"])

    # Strength training signal — meaningful number of workout sessions.
    if len(selected) < 2:
        workout_count = metrics.get("workout_count", 0)
        # Hevy summary data is passed at the top level in some calling contexts
        if workout_count >= 3:
            _add_topics(selected, ["strength_training"])

    # Default fallback: if nothing triggered, surface the two most broadly
    # applicable topics.
    if not selected:
        selected = ["strength_training", "sleep"]

    return selected[:2]


def _add_topics(selected: list[str], candidates: list[str]) -> None:
    """Add candidates to selected list without duplicates, up to 2 total."""
    for topic in candidates:
        if topic not in selected and len(selected) < 2:
            selected.append(topic)


def load_topic(topic_key: str) -> str:
    """Load and return the full text of a knowledge base file."""
    filename = TOPIC_FILES.get(topic_key)
    if filename is None:
        raise KeyError(
            f"Unknown topic key {topic_key!r}. Valid keys: {list(TOPIC_FILES)}"
        )

    path = KNOWLEDGE_BASE_DIR / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Knowledge base file not found: {path}. "
            "Ensure knowledge_base/ directory is present."
        )

    return path.read_text(encoding="utf-8")


def summarise_to_budget(text: str, max_chars: int = 1500) -> str:
    """
    Truncate text to max_chars at a paragraph boundary.
    Adds '...[truncated for brevity]' if truncated.
    """
    if len(text) <= max_chars:
        return text

    # Find the last paragraph break (double newline) within the budget.
    truncation_point = text.rfind("\n\n", 0, max_chars)

    if truncation_point == -1:
        # No paragraph boundary found; fall back to last newline.
        truncation_point = text.rfind("\n", 0, max_chars)

    if truncation_point == -1:
        # No newline at all; hard truncate at max_chars.
        truncation_point = max_chars

    return text[:truncation_point].rstrip() + "\n\n...[truncated for brevity]"


def get_knowledge_context(metrics: dict) -> str:
    """
    Select relevant topics, load and summarise them, return a formatted
    string block ready for injection into the Claude prompt.

    Returns a string like:

    [KNOWLEDGE BASE — STRENGTH TRAINING]
    <content>

    [KNOWLEDGE BASE — HRV INTERPRETATION]
    <content>

    Returns empty string if knowledge_base/ dir doesn't exist.
    """
    if not KNOWLEDGE_BASE_DIR.exists():
        return ""

    topics = select_relevant_topics(metrics)

    sections: list[str] = []
    for topic_key in topics:
        try:
            raw_text = load_topic(topic_key)
        except FileNotFoundError:
            # Gracefully skip missing files rather than crashing the review.
            continue

        summarised = summarise_to_budget(raw_text, max_chars=1500)
        label = TOPIC_LABELS.get(topic_key, topic_key.upper().replace("_", " "))
        sections.append(f"[KNOWLEDGE BASE — {label}]\n{summarised}")

    return "\n\n".join(sections)
