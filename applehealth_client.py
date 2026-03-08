"""Apple Health weight data client for AIFitnessSummary.

Eufy smart scales sync weight to Apple Health on iOS.  Since Apple Health
has no REST API, this client reads weight data exported via an iOS Shortcut.

Two import modes are supported (configure one in .env):

1. **File-based** (``APPLE_HEALTH_WEIGHT_FILE``):
   An iOS Shortcut writes weight entries as JSON to a synced file (iCloud
   Drive, Dropbox, or local path).  This client reads that file directly.

2. **Webhook-based** (``APPLE_HEALTH_WEIGHT_URL``):
   An iOS Shortcut POSTs weight data to a webhook (e.g. a simple endpoint
   you host, or a service like Make/Zapier).  This client GETs the latest
   entries from that URL.

Expected JSON format (array of entries):
    [
        {"date": "2026-03-01", "weight_kg": 82.5},
        {"date": "2026-03-02", "weight_kg": 82.3},
        ...
    ]

The iOS Shortcut to generate this is documented in the README.

Required environment variables (set ONE of these):
    APPLE_HEALTH_WEIGHT_FILE  – path to the synced JSON file
    APPLE_HEALTH_WEIGHT_URL   – URL to GET weight data from
"""

import datetime
import json
import os
from pathlib import Path

import requests


class AppleHealthClient:
    """Fetch weight data exported from Apple Health via iOS Shortcuts."""

    def __init__(
        self,
        weight_file: str = None,
        weight_url: str = None,
    ):
        self._weight_file = weight_file or os.getenv("APPLE_HEALTH_WEIGHT_FILE")
        self._weight_url = weight_url or os.getenv("APPLE_HEALTH_WEIGHT_URL")
        if not self._weight_file and not self._weight_url:
            raise RuntimeError(
                "Apple Health integration requires either "
                "APPLE_HEALTH_WEIGHT_FILE or APPLE_HEALTH_WEIGHT_URL."
            )

    def fetch_weight(self, start: datetime.date, end: datetime.date) -> dict:
        """Read weight data and filter to the given date range.

        Returns a dict matching the shape of GarminClient.fetch_body_composition()
        so the data can be merged seamlessly:
            {
                "entries": [{"date": "2026-03-01", "weight_kg": 82.5}, ...],
                "latest_weight_kg": 82.3,
                "avg_weight_kg": 82.4,
                "source": "apple_health",
            }
        """
        raw_entries = self._load_entries()

        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")

        entries = []
        for entry in raw_entries:
            date_str = entry.get("date", "")
            weight = entry.get("weight_kg")
            if not date_str or weight is None:
                continue
            if start_str <= date_str <= end_str:
                entries.append({
                    "date": date_str,
                    "weight_kg": round(float(weight), 1),
                })

        # Deduplicate: keep latest entry per day
        by_date: dict[str, dict] = {}
        for e in entries:
            by_date[e["date"]] = e
        entries = sorted(by_date.values(), key=lambda e: e["date"])

        weights = [e["weight_kg"] for e in entries]
        return {
            "entries": entries,
            "latest_weight_kg": entries[-1]["weight_kg"] if entries else None,
            "avg_weight_kg": round(sum(weights) / len(weights), 1) if weights else None,
            "source": "apple_health",
        }

    def _load_entries(self) -> list[dict]:
        """Load raw weight entries from the configured source."""
        if self._weight_file:
            return self._load_from_file()
        return self._load_from_url()

    def _load_from_file(self) -> list[dict]:
        """Read entries from a local/synced JSON file."""
        path = Path(self._weight_file).expanduser()
        if not path.exists():
            print(f"Warning: Apple Health weight file not found: {path}")
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        # Support a wrapper object with an "entries" key
        return data.get("entries", data.get("data", []))

    def _load_from_url(self) -> list[dict]:
        """GET entries from a webhook URL."""
        resp = requests.get(self._weight_url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        return data.get("entries", data.get("data", []))


def get_applehealth_client() -> "AppleHealthClient | None":
    """Return an AppleHealthClient if configured, else None."""
    if os.getenv("APPLE_HEALTH_WEIGHT_FILE") or os.getenv("APPLE_HEALTH_WEIGHT_URL"):
        try:
            return AppleHealthClient()
        except Exception as e:
            print(f"Warning: Apple Health initialisation failed: {e}")
            return None
    return None
