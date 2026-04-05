"""Garmin Connect data client for AIFitnessSummary.

Fetches only the metrics specified in the Health & Performance Digest proposal:
- Sleep: duration, bedtime consistency, efficiency, respiratory rate, overnight RHR
- Recovery: 7-day RHR, HRV status label, Training Status (block only)
- Running: activities with HR zones for intensity distribution, pace-at-threshold-HR
- VO2max (block trend only)
- Body composition (weight)

Excluded per proposal (Section 4.7):
- Sleep score, sleep stages (deep/REM/light), Body Battery, daily stress,
  step count, daily HRV score, race predictions, endurance score, hill score,
  fitness age, lactate threshold, morning readiness, sweat loss, SpO2,
  running dynamics (cadence/power/GCT/VO)
"""

import datetime
import math
import os
import re
import statistics
import time
from pathlib import Path

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectTooManyRequestsError,
)

from config import DATE_FORMAT

TOKENSTORE = os.path.expanduser("~/.garminconnect")


def _date_range(start: datetime.date, end: datetime.date) -> list[datetime.date]:
    """Return list of dates from start to end inclusive."""
    days = (end - start).days + 1
    return [start + datetime.timedelta(days=i) for i in range(days)]


def _safe_get(func, *args, retries: int = 3, **kwargs):
    """Call func with exponential-backoff retry on rate-limit errors."""
    delay = 5
    for attempt in range(retries):
        try:
            return func(*args, **kwargs)
        except GarminConnectTooManyRequestsError:
            if attempt == retries - 1:
                raise
            print(f"Rate limited by Garmin. Waiting {delay}s before retry {attempt + 2}/{retries}...")
            time.sleep(delay)
            delay *= 2
    return None


def _clean_phrase(phrase: str | None) -> str | None:
    """Convert 'TRAINING_STATUS_2' -> 'Training Status'."""
    if not phrase:
        return None
    cleaned = re.sub(r'_\d+$', '', phrase)
    return cleaned.replace('_', ' ').title()


def _get_primary_data(mapping: dict | None) -> dict:
    """Return the primary-device entry from a deviceId-keyed dict."""
    if not mapping:
        return {}
    for v in mapping.values():
        if isinstance(v, dict) and v.get("primaryTrainingDevice"):
            return v
    return next(iter(mapping.values()), {})


class GarminClient:
    """Fetches health and activity data from Garmin Connect.

    Authentication uses garth OAuth tokens stored at ~/.garminconnect.
    First-time setup requires email/password + MFA code. After that,
    tokens auto-refresh for ~1 year.
    """

    def __init__(self, email: str | None = None, password: str | None = None):
        email = email or os.environ.get("GARMIN_EMAIL", "")
        password = password or os.environ.get("GARMIN_PASSWORD", "")
        self._client = self._login(email, password)
        self._training_status_cache: dict[str, dict] = {}

    @staticmethod
    def _login(email: str, password: str) -> Garmin:
        """Authenticate with Garmin Connect.

        Strategy:
        1. Try loading cached OAuth tokens (no credentials needed)
        2. Fall back to credential + MFA login if tokens missing/expired
        """
        # Attempt 1: load saved tokens
        try:
            client = Garmin()
            client.login(TOKENSTORE)
            print("Loaded Garmin session from saved tokens.")
            return client
        except Exception:
            pass

        if not email or not password:
            raise RuntimeError(
                "No saved Garmin tokens found and GARMIN_EMAIL/GARMIN_PASSWORD "
                "not set. Run locally first to complete initial authentication."
            )

        # Attempt 2: credential + MFA login
        print("No saved Garmin session found. Starting first-time login...")
        print("Garmin will email you a 6-digit verification code.")
        try:
            client = Garmin(email=email, password=password, is_cn=False, return_on_mfa=True)
            result, mfa_data = client.login()
            if result == "needs_mfa":
                mfa_code = input("Enter the 6-digit code from your Garmin email: ").strip()
                client.resume_login(mfa_data, mfa_code)

            tokenstore_path = Path(TOKENSTORE)
            tokenstore_path.mkdir(mode=0o700, exist_ok=True)
            client.garth.dump(str(tokenstore_path))
            print(f"Session saved to {TOKENSTORE}. No code needed again for ~1 year.")
            return client
        except GarminConnectAuthenticationError as exc:
            raise RuntimeError(
                "Garmin authentication failed. Check GARMIN_EMAIL and GARMIN_PASSWORD."
            ) from exc

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_training_status(self, end: datetime.date) -> dict:
        """Fetch training status once and cache for reuse."""
        key = end.strftime(DATE_FORMAT)
        if key not in self._training_status_cache:
            result = _safe_get(self._client.get_training_status, key)
            self._training_status_cache[key] = result or {}
        return self._training_status_cache[key]

    # ------------------------------------------------------------------
    # Sleep (Section 4.1)
    # ------------------------------------------------------------------

    def fetch_sleep(self, start: datetime.date, end: datetime.date) -> dict:
        """Sleep metrics per proposal Section 4.1.

        Returns:
        - avg_total_h: average sleep duration (hours)
        - bedtime_consistency_sd_min: SD of bedtime in minutes (lower = better)
        - avg_sleep_efficiency_pct: time asleep / time in bed * 100
        - nights_tracked: count of nights with data

        Excluded: sleep stages (deep/REM/light), sleep score.
        """
        durations = []
        efficiencies = []
        bedtimes_minutes = []  # minutes from midnight for SD calculation

        for day in _date_range(start, end):
            data = _safe_get(self._client.get_sleep_data, day.strftime(DATE_FORMAT))
            if not data:
                continue
            summary = data.get("dailySleepDTO") or {}
            if not summary:
                continue

            total_sec = summary.get("sleepTimeSeconds") or 0
            if total_sec == 0:
                continue

            durations.append(round(total_sec / 3600, 2))

            # Sleep efficiency: time asleep / time in bed
            # sleepTimeSeconds = actual sleep; sleepStartTimestampLocal/sleepEndTimestampLocal = in-bed
            start_ts = summary.get("sleepStartTimestampLocal")
            end_ts = summary.get("sleepEndTimestampLocal")
            if start_ts and end_ts:
                # Timestamps are in milliseconds
                if isinstance(start_ts, (int, float)) and isinstance(end_ts, (int, float)):
                    time_in_bed_sec = (end_ts - start_ts) / 1000
                    if time_in_bed_sec > 0:
                        efficiency = (total_sec / time_in_bed_sec) * 100
                        efficiencies.append(round(min(efficiency, 100), 1))

                    # Bedtime as minutes from midnight for consistency calculation
                    bedtime_dt = datetime.datetime.fromtimestamp(start_ts / 1000)
                    minutes_from_midnight = bedtime_dt.hour * 60 + bedtime_dt.minute
                    # Wrap around: if bedtime is after 6pm, treat as negative offset from midnight
                    if minutes_from_midnight > 360:  # after 6am = likely still counting from previous day
                        if minutes_from_midnight < 1080:  # before 6pm = unusual, keep as-is
                            pass
                        else:  # after 6pm = evening bedtime, wrap to negative
                            minutes_from_midnight = minutes_from_midnight - 1440
                    bedtimes_minutes.append(minutes_from_midnight)

        bedtime_sd = None
        if len(bedtimes_minutes) >= 2:
            bedtime_sd = round(statistics.stdev(bedtimes_minutes), 0)

        return {
            "avg_total_h": round(sum(durations) / len(durations), 2) if durations else None,
            "bedtime_consistency_sd_min": bedtime_sd,
            "avg_sleep_efficiency_pct": round(sum(efficiencies) / len(efficiencies), 1) if efficiencies else None,
            "nights_tracked": len(durations),
        }

    # ------------------------------------------------------------------
    # Recovery: Resting HR and Respiration (Sections 4.1, 4.4)
    # ------------------------------------------------------------------

    def fetch_resting_hr(self, start: datetime.date, end: datetime.date) -> dict:
        """7-day average resting heart rate.

        Returns avg_resting_hr (bpm) — the primary recovery marker.
        Persistent elevation of 5+ bpm above baseline = overtraining signal.
        """
        resting_list = []
        for day in _date_range(start, end):
            data = _safe_get(self._client.get_heart_rates, day.strftime(DATE_FORMAT))
            if not data:
                continue
            resting = data.get("restingHeartRate")
            if resting:
                resting_list.append(resting)

        return {
            "avg_resting_hr": round(sum(resting_list) / len(resting_list), 1) if resting_list else None,
            "resting_hr_values": resting_list,
        }

    def fetch_sleep_respiration(self, start: datetime.date, end: datetime.date) -> dict:
        """Average respiratory rate during sleep (breaths/min).

        Per Galpin: meaningful sleep quality signal. Elevated or variable
        respiratory rate can flag early illness or overtraining stress.
        """
        sleep_vals = []
        for day in _date_range(start, end):
            data = _safe_get(self._client.get_respiration_data, day.strftime(DATE_FORMAT))
            if not data:
                continue
            sleeping = data.get("avgSleepRespirationValue")
            if sleeping:
                sleep_vals.append(sleeping)

        return {
            "avg_sleep_respiration_brpm": round(sum(sleep_vals) / len(sleep_vals), 1) if sleep_vals else None,
        }

    # ------------------------------------------------------------------
    # Recovery: HRV (Section 4.4)
    # ------------------------------------------------------------------

    def fetch_hrv_status(self, start: datetime.date, end: datetime.date) -> dict:
        """HRV 7-day status label only (Balanced / Unbalanced / Poor).

        Per Galpin: HRV is a better recovery marker than RHR but compare
        only to your own baseline. The 7-day label smooths daily noise.
        Raw ms values are NOT returned (proposal Section 4.7 exclusion).
        """
        statuses = []
        for day in _date_range(start, end):
            data = _safe_get(self._client.get_hrv_data, day.strftime(DATE_FORMAT))
            if not data:
                continue
            summary = data.get("hrvSummary") or {}
            status = summary.get("status")
            if status:
                statuses.append(status)

        # Return the most recent status label (the 7-day rolling label)
        latest_status = statuses[-1] if statuses else None

        return {
            "hrv_status_label": latest_status,
        }

    # ------------------------------------------------------------------
    # Recovery: Training Status (Section 4.4 - block check-in only)
    # ------------------------------------------------------------------

    def fetch_training_status(self, end: datetime.date) -> dict:
        """Training Status label from Garmin.

        Composite of VO2max trend, HRV, and acute training load.
        'Productive' = correct load; 'Maintaining' = under-stimulated;
        'Overreaching' = load exceeds adaptation capacity.
        Reviewed at block level only per proposal.
        """
        data = self._get_training_status(end)
        if not data:
            return {"training_status": None}

        status_map = (data.get("mostRecentTrainingStatus") or {}).get("latestTrainingStatusData") or {}
        status_dto = _get_primary_data(status_map)
        status_phrase = _clean_phrase(status_dto.get("trainingStatusFeedbackPhrase"))

        return {"training_status": status_phrase}

    # ------------------------------------------------------------------
    # Running (Section 4.3)
    # ------------------------------------------------------------------

    def fetch_runs(self, start: datetime.date, end: datetime.date) -> dict:
        """Running activities with data needed for proposal metrics.

        Returns per-run: date, distance_km, duration_min, avg_hr, hr_zones.
        Computes: total_distance_km, intensity distribution (easy/hard km %),
        run_count.

        Excluded: running dynamics (cadence, power, GCT, vertical oscillation).
        """
        data = _safe_get(
            self._client.get_activities_by_date,
            start.strftime(DATE_FORMAT),
            end.strftime(DATE_FORMAT),
            "running",
        )
        if not data:
            return {
                "runs": [], "run_count": 0, "total_distance_km": 0.0,
                "easy_km": 0.0, "hard_km": 0.0, "easy_pct": None, "hard_pct": None,
            }

        runs = []
        total_easy_km = 0.0
        total_hard_km = 0.0

        for activity in data:
            distance_m = activity.get("distance") or 0
            duration_s = activity.get("duration") or 0
            date = (activity.get("startTimeLocal") or "")[:10]
            activity_id = activity.get("activityId")

            distance_km = round(distance_m / 1000, 2)
            duration_min = round(duration_s / 60, 1)
            avg_pace = round(duration_min / distance_km, 2) if distance_km > 0 else None
            avg_hr = activity.get("averageHR")

            # HR zone distribution for intensity classification
            hr_zones = {}
            easy_km_run = distance_km  # default: all easy if no zone data
            hard_km_run = 0.0

            if activity_id:
                zones_data = _safe_get(self._client.get_activity_hr_in_timezones, activity_id)
                if zones_data and isinstance(zones_data, list):
                    total_secs = sum(z.get("secsInZone", 0) for z in zones_data)
                    if total_secs > 0:
                        for z in zones_data:
                            zone_num = z.get("zoneNumber")
                            if zone_num:
                                pct = z.get("secsInZone", 0) / total_secs
                                hr_zones[f"zone{zone_num}_pct"] = round(pct * 100, 1)

                        # Easy = Z1+Z2, Hard = Z3+Z4+Z5
                        easy_pct = sum(
                            z.get("secsInZone", 0) for z in zones_data
                            if z.get("zoneNumber") in (1, 2)
                        ) / total_secs
                        hard_pct = 1.0 - easy_pct
                        easy_km_run = round(distance_km * easy_pct, 2)
                        hard_km_run = round(distance_km * hard_pct, 2)

            total_easy_km += easy_km_run
            total_hard_km += hard_km_run

            runs.append({
                "date": date,
                "distance_km": distance_km,
                "duration_min": duration_min,
                "avg_pace_min_km": avg_pace,
                "avg_hr": avg_hr,
                "hr_zones": hr_zones,
                "easy_km": easy_km_run,
                "hard_km": hard_km_run,
            })

        total_km = round(total_easy_km + total_hard_km, 2)
        return {
            "runs": sorted(runs, key=lambda r: r["date"]),
            "run_count": len(runs),
            "total_distance_km": total_km,
            "easy_km": round(total_easy_km, 2),
            "hard_km": round(total_hard_km, 2),
            "easy_pct": round(total_easy_km / total_km * 100, 1) if total_km > 0 else None,
            "hard_pct": round(total_hard_km / total_km * 100, 1) if total_km > 0 else None,
        }

    # ------------------------------------------------------------------
    # VO2max (Section 4.3 - block trend only)
    # ------------------------------------------------------------------

    def fetch_vo2max(self, end: datetime.date) -> dict:
        """Latest VO2max estimate. Directional indicator only, not week-to-week."""
        data = self._get_training_status(end)
        if not data:
            return {"vo2_max": None}
        generic = (data.get("mostRecentVO2Max") or {}).get("generic") or {}
        return {
            "vo2_max": generic.get("vo2MaxPreciseValue") or generic.get("vo2MaxValue"),
        }

    # ------------------------------------------------------------------
    # Body Composition (Section 4.5 - weight only)
    # ------------------------------------------------------------------

    def fetch_body_composition(self, start: datetime.date, end: datetime.date) -> dict:
        """Weight data for bodyweight trend tracking."""
        data = _safe_get(
            self._client.get_body_composition,
            start.strftime(DATE_FORMAT),
            end.strftime(DATE_FORMAT),
        )
        if not data:
            return {"entries": [], "latest_weight_kg": None, "avg_weight_kg": None}

        raw = data if isinstance(data, list) else (
            data.get("dateWeightList") or data.get("bodyCompositionList") or []
        )
        entries = []
        for entry in raw:
            weight_g = entry.get("weight")
            if not weight_g:
                continue
            entries.append({
                "date": entry.get("calendarDate") or entry.get("date", ""),
                "weight_kg": round(weight_g / 1000, 1),
            })

        entries.sort(key=lambda e: e["date"])
        weights = [e["weight_kg"] for e in entries]
        return {
            "entries": entries,
            "latest_weight_kg": entries[-1]["weight_kg"] if entries else None,
            "avg_weight_kg": round(sum(weights) / len(weights), 1) if weights else None,
        }

    # ------------------------------------------------------------------
    # Aggregator
    # ------------------------------------------------------------------

    def collect_all(self, start: datetime.date, end: datetime.date) -> dict:
        """Fetch all proposal-aligned metrics and return as a single dict."""
        print("Fetching Garmin data...")
        return {
            "sleep": self.fetch_sleep(start, end),
            "resting_hr": self.fetch_resting_hr(start, end),
            "sleep_respiration": self.fetch_sleep_respiration(start, end),
            "hrv": self.fetch_hrv_status(start, end),
            "runs": self.fetch_runs(start, end),
            "vo2max": self.fetch_vo2max(end),
            "body_composition": self.fetch_body_composition(start, end),
            "training_status": self.fetch_training_status(end),
        }
