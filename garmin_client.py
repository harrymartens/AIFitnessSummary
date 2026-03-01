import datetime
import os
import time
from pathlib import Path

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from config import DATE_FORMAT

# Garth saves OAuth tokens here so subsequent runs don't need credentials/2FA
TOKENSTORE = os.path.expanduser("~/.garminconnect")


def _date_range(start: datetime.date, end: datetime.date) -> list[datetime.date]:
    """Return list of dates from start to end inclusive."""
    days = (end - start).days + 1
    return [start + datetime.timedelta(days=i) for i in range(days)]


def _safe_get(func, *args, retries: int = 3, **kwargs):
    """Call func(*args, **kwargs) with exponential-backoff retry on rate-limit errors."""
    delay = 5
    for attempt in range(retries):
        try:
            return func(*args, **kwargs)
        except GarminConnectTooManyRequestsError:
            if attempt == retries - 1:
                raise
            print(f"Rate limited by Garmin. Waiting {delay}s before retry {attempt + 2}/{retries}…")
            time.sleep(delay)
            delay *= 2
    return None


class GarminClient:
    """Fetches health and activity data from Garmin Connect."""

    def __init__(self, email: str | None = None, password: str | None = None):
        email = email or os.environ["GARMIN_EMAIL"]
        password = password or os.environ["GARMIN_PASSWORD"]
        self._client = self._login(email, password)

    @staticmethod
    def _login(email: str, password: str) -> Garmin:
        """Authenticate with Garmin Connect.

        Tries loading cached OAuth tokens from TOKENSTORE first — this is
        what all cron/automated runs use after the initial setup.

        On first run (or after token expiry ~1 year), falls back to a full
        credential + MFA login using return_on_mfa=True so the 6-digit code
        is explicitly prompted and fed to resume_login(). Tokens are then
        saved and future runs are fully non-interactive.
        """
        # --- Attempt 1: load saved tokens (no credentials or MFA needed) ---
        try:
            client = Garmin()
            client.login(TOKENSTORE)
            print("Loaded Garmin session from saved tokens.")
            return client
        except Exception:
            pass  # no tokens yet or expired — fall through to fresh login

        # --- Attempt 2: full credential + MFA login ---
        print("No saved Garmin session found. Starting first-time login…")
        print(
            "Garmin will email you a 6-digit verification code.\n"
            "You only need to do this once — tokens are saved for ~1 year."
        )
        try:
            client = Garmin(email=email, password=password, is_cn=False, return_on_mfa=True)
            result, mfa_data = client.login()
            if result == "needs_mfa":
                mfa_code = input("Enter the 6-digit code from your Garmin email: ").strip()
                client.resume_login(mfa_data, mfa_code)

            # Persist tokens — cron jobs and all future runs will use these
            tokenstore_path = Path(TOKENSTORE)
            tokenstore_path.mkdir(mode=0o700, exist_ok=True)
            client.garth.dump(str(tokenstore_path))
            print(f"Session saved to {TOKENSTORE}. No code needed again for ~1 year.")
            return client
        except GarminConnectAuthenticationError as exc:
            raise RuntimeError(
                "Garmin authentication failed — check GARMIN_EMAIL and GARMIN_PASSWORD."
            ) from exc

    # ------------------------------------------------------------------
    # Individual metric fetchers
    # ------------------------------------------------------------------

    def fetch_stats(self, start: datetime.date, end: datetime.date) -> dict:
        """Average daily steps and active/intensity minutes over the period."""
        steps_list, active_list, intensity_list = [], [], []
        for day in _date_range(start, end):
            data = _safe_get(self._client.get_stats, day.strftime(DATE_FORMAT))
            if not data:
                continue
            if data.get("totalSteps") is not None:
                steps_list.append(data["totalSteps"])
            if data.get("activeKilocalories") is not None:
                active_list.append((data.get("moderateIntensityMinutes") or 0) +
                                   (data.get("vigorousIntensityMinutes") or 0) * 2)
            if data.get("moderateIntensityMinutes") is not None:
                intensity_list.append(
                    (data.get("moderateIntensityMinutes") or 0) +
                    (data.get("vigorousIntensityMinutes") or 0)
                )

        return {
            "avg_daily_steps": int(sum(steps_list) / len(steps_list)) if steps_list else None,
            "avg_active_minutes": int(sum(active_list) / len(active_list)) if active_list else None,
            "avg_intensity_minutes": int(sum(intensity_list) / len(intensity_list)) if intensity_list else None,
            "days_with_data": len(steps_list),
        }

    def fetch_heart_rates(self, start: datetime.date, end: datetime.date) -> dict:
        """Average resting heart rate and daily trend."""
        resting_list = []
        trend = []
        for day in _date_range(start, end):
            data = _safe_get(self._client.get_heart_rates, day.strftime(DATE_FORMAT))
            if not data:
                continue
            resting = data.get("restingHeartRate")
            if resting:
                resting_list.append(resting)
                trend.append({"date": day.strftime(DATE_FORMAT), "resting_hr": resting})

        return {
            "avg_resting_hr": round(sum(resting_list) / len(resting_list), 1) if resting_list else None,
            "daily_trend": trend,
        }

    def fetch_sleep(self, start: datetime.date, end: datetime.date) -> dict:
        """Per-night sleep breakdown (total, deep, REM, light, awake) and averages."""
        nightly = []
        for day in _date_range(start, end):
            data = _safe_get(self._client.get_sleep_data, day.strftime(DATE_FORMAT))
            if not data:
                continue
            summary = data.get("dailySleepDTO") or {}
            if not summary:
                continue
            total_sec = summary.get("sleepTimeSeconds") or 0
            deep_sec = summary.get("deepSleepSeconds") or 0
            rem_sec = summary.get("remSleepSeconds") or 0
            light_sec = summary.get("lightSleepSeconds") or 0
            awake_sec = summary.get("awakeSleepSeconds") or 0
            nightly.append({
                "date": day.strftime(DATE_FORMAT),
                "total_h": round(total_sec / 3600, 2),
                "deep_h": round(deep_sec / 3600, 2),
                "rem_h": round(rem_sec / 3600, 2),
                "light_h": round(light_sec / 3600, 2),
                "awake_h": round(awake_sec / 3600, 2),
            })

        def _avg(key: str) -> float | None:
            vals = [n[key] for n in nightly if n[key] is not None]
            return round(sum(vals) / len(vals), 2) if vals else None

        return {
            "nightly": nightly,
            "avg_total_h": _avg("total_h"),
            "avg_deep_h": _avg("deep_h"),
            "avg_rem_h": _avg("rem_h"),
            "avg_light_h": _avg("light_h"),
            "avg_awake_h": _avg("awake_h"),
        }

    def fetch_stress(self, start: datetime.date, end: datetime.date) -> dict:
        """Average stress level over the period."""
        scores = []
        daily = []
        for day in _date_range(start, end):
            data = _safe_get(self._client.get_stress_data, day.strftime(DATE_FORMAT))
            if not data:
                continue
            avg = data.get("avgStressLevel")
            if avg and avg > 0:
                scores.append(avg)
                daily.append({"date": day.strftime(DATE_FORMAT), "avg_stress": avg})

        return {
            "avg_stress": round(sum(scores) / len(scores), 1) if scores else None,
            "daily": daily,
        }

    def fetch_body_battery(self, start: datetime.date, end: datetime.date) -> dict:
        """Body battery charged/drained values over the period."""
        start_str = start.strftime(DATE_FORMAT)
        end_str = end.strftime(DATE_FORMAT)
        data = _safe_get(self._client.get_body_battery, start_str, end_str)
        if not data:
            return {"daily": [], "avg_max": None, "avg_min": None}

        daily = []
        for entry in data:
            date = entry.get("date") or entry.get("calendarDate", "")
            charged = entry.get("charged")
            drained = entry.get("drained")
            if date:
                daily.append({"date": date, "charged": charged, "drained": drained})

        avg_max = round(sum(d["charged"] for d in daily if d["charged"] is not None) /
                        max(len([d for d in daily if d["charged"] is not None]), 1), 1)
        avg_min = round(sum(d["drained"] for d in daily if d["drained"] is not None) /
                        max(len([d for d in daily if d["drained"] is not None]), 1), 1)
        return {"daily": daily, "avg_max": avg_max, "avg_min": avg_min}

    def fetch_hrv(self, start: datetime.date, end: datetime.date) -> dict:
        """Daily HRV status and weekly average."""
        daily = []
        values = []
        for day in _date_range(start, end):
            data = _safe_get(self._client.get_hrv_data, day.strftime(DATE_FORMAT))
            if not data:
                continue
            summary = data.get("hrvSummary") or {}
            status = summary.get("status")
            weekly_avg = summary.get("weeklyAvg")
            last_night = summary.get("lastNight")
            if status or last_night:
                daily.append({
                    "date": day.strftime(DATE_FORMAT),
                    "status": status,
                    "last_night_avg_ms": last_night,
                })
            if weekly_avg:
                values.append(weekly_avg)

        return {
            "daily": daily,
            "period_avg_ms": round(sum(values) / len(values), 1) if values else None,
        }

    def fetch_training_load(self, start: datetime.date, end: datetime.date) -> dict:
        """Training load and status for each day."""
        daily = []
        for day in _date_range(start, end):
            data = _safe_get(self._client.get_training_status, day.strftime(DATE_FORMAT))
            if not data:
                continue
            load = data.get("trainingLoad")
            status = data.get("trainingLoadStatus") or data.get("status")
            if load or status:
                daily.append({
                    "date": day.strftime(DATE_FORMAT),
                    "training_load": load,
                    "status": status,
                })

        latest_status = daily[-1]["status"] if daily else None
        avg_load = round(
            sum(d["training_load"] for d in daily if d["training_load"] is not None) /
            max(len([d for d in daily if d["training_load"] is not None]), 1), 1
        )
        return {"daily": daily, "avg_load": avg_load, "latest_status": latest_status}

    # ------------------------------------------------------------------
    # Aggregator
    # ------------------------------------------------------------------

    def collect_all(self, start: datetime.date, end: datetime.date) -> dict:
        """Fetch all metrics and return as a single dict."""
        print("Fetching Garmin data…")
        return {
            "stats": self.fetch_stats(start, end),
            "heart_rate": self.fetch_heart_rates(start, end),
            "sleep": self.fetch_sleep(start, end),
            "stress": self.fetch_stress(start, end),
            "body_battery": self.fetch_body_battery(start, end),
            "hrv": self.fetch_hrv(start, end),
            "training_load": self.fetch_training_load(start, end),
        }
