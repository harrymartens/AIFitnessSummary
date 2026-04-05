"""Nutrition and weight data client for AIFitnessSummary.

Supports two data sources:
1. Apple Health (via iOS Shortcuts export) — weight, calories, protein
2. MacroFactor (syncs to Apple Health) — calories, protein, expenditure

Data is exported from Apple Health via an iOS Shortcut that writes JSON
to a synced file or posts to a webhook.

Expected JSON format:
    [
        {
            "date": "2026-03-01",
            "weight_kg": 82.5,
            "calories": 2850,
            "protein_g": 185,
            "expenditure": 2700
        },
        ...
    ]

Fields are optional — entries may contain only weight, only nutrition, or both.
MacroFactor syncs calories/protein/expenditure to Apple Health automatically.
"""

import datetime
import json
import os
import re
from pathlib import Path

import requests


def _normalise_date(raw: str) -> str | None:
    """Convert various date formats to YYYY-MM-DD."""
    raw = raw.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return raw
    cleaned = re.sub(r"\s+at\s+\d{1,2}:\d{2}\s*[ap]m", "", raw, flags=re.IGNORECASE)
    for fmt in ("%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


class NutritionClient:
    """Fetch nutrition and weight data from Apple Health / MacroFactor exports."""

    def __init__(
        self,
        data_file: str = None,
        data_url: str = None,
    ):
        self._data_file = data_file or os.getenv("APPLE_HEALTH_WEIGHT_FILE")
        self._data_url = data_url or os.getenv("APPLE_HEALTH_WEIGHT_URL")
        if not self._data_file and not self._data_url:
            raise RuntimeError(
                "Nutrition data requires either "
                "APPLE_HEALTH_WEIGHT_FILE or APPLE_HEALTH_WEIGHT_URL."
            )

    def fetch_data(self, start: datetime.date, end: datetime.date) -> dict:
        """Read nutrition and weight data, filtered to date range.

        Returns:
            weight: {entries, latest_weight_kg, avg_weight_kg}
            nutrition: {avg_daily_calories, avg_daily_protein_g, avg_expenditure}
        """
        raw_entries = self._load_entries()

        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")

        weight_entries = []
        calorie_values = []
        protein_values = []
        expenditure_values = []

        for entry in raw_entries:
            date_str = _normalise_date(str(entry.get("date", "")))
            if not date_str or not (start_str <= date_str <= end_str):
                continue

            # Weight
            weight = entry.get("weight_kg")
            if weight is not None:
                weight_entries.append({
                    "date": date_str,
                    "weight_kg": round(float(weight), 1),
                })

            # Nutrition (from MacroFactor via Apple Health)
            calories = entry.get("calories")
            if calories is not None:
                calorie_values.append(float(calories))

            protein = entry.get("protein_g")
            if protein is not None:
                protein_values.append(float(protein))

            expenditure = entry.get("expenditure")
            if expenditure is not None:
                expenditure_values.append(float(expenditure))

        # Deduplicate weight by date (keep latest)
        by_date: dict[str, dict] = {}
        for e in weight_entries:
            by_date[e["date"]] = e
        weight_entries = sorted(by_date.values(), key=lambda e: e["date"])

        weights = [e["weight_kg"] for e in weight_entries]

        return {
            "weight": {
                "entries": weight_entries,
                "latest_weight_kg": weight_entries[-1]["weight_kg"] if weight_entries else None,
                "avg_weight_kg": round(sum(weights) / len(weights), 1) if weights else None,
            },
            "nutrition": {
                "avg_daily_calories": round(sum(calorie_values) / len(calorie_values)) if calorie_values else None,
                "avg_daily_protein_g": round(sum(protein_values) / len(protein_values), 1) if protein_values else None,
                "avg_expenditure": round(sum(expenditure_values) / len(expenditure_values)) if expenditure_values else None,
                "days_logged": len(calorie_values),
            },
        }

    def _load_entries(self) -> list[dict]:
        """Load raw entries from the configured source."""
        if self._data_file:
            return self._load_from_file()
        return self._load_from_url()

    def _load_from_file(self) -> list[dict]:
        path = Path(self._data_file).expanduser()
        if not path.exists():
            print(f"Warning: Health data file not found: {path}")
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return data.get("entries", data.get("data", []))

    def _load_from_url(self) -> list[dict]:
        resp = requests.get(self._data_url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        return data.get("entries", data.get("data", []))


def get_nutrition_client() -> "NutritionClient | None":
    """Return a NutritionClient if configured, else None."""
    if os.getenv("APPLE_HEALTH_WEIGHT_FILE") or os.getenv("APPLE_HEALTH_WEIGHT_URL"):
        try:
            return NutritionClient()
        except Exception as e:
            print(f"Warning: Nutrition client initialisation failed: {e}")
            return None
    return None
