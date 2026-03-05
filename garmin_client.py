import datetime
import os
import re
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


def _clean_phrase(phrase: str | None) -> str | None:
    """Convert 'TRAINING_STATUS_2' → 'Training Status'."""
    if not phrase:
        return None
    cleaned = re.sub(r'_\d+$', '', phrase)
    return cleaned.replace('_', ' ').title()


def _fmt_duration(seconds: int | float | None) -> str | None:
    """Format a seconds value as H:MM:SS or M:SS string."""
    if seconds is None:
        return None
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _get_primary_data(mapping: dict | None) -> dict:
    """Return the primary-device entry from a deviceId-keyed dict."""
    if not mapping:
        return {}
    for v in mapping.values():
        if isinstance(v, dict) and v.get("primaryTrainingDevice"):
            return v
    return next(iter(mapping.values()), {})


class GarminClient:
    """Fetches health and activity data from Garmin Connect."""

    def __init__(self, email: str | None = None, password: str | None = None):
        email = email or os.environ["GARMIN_EMAIL"]
        password = password or os.environ["GARMIN_PASSWORD"]
        self._client = self._login(email, password)
        self._training_status_cache: dict[str, dict] = {}

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
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_training_status(self, end: datetime.date) -> dict:
        """Fetch training status once and cache for reuse within a single run."""
        key = end.strftime(DATE_FORMAT)
        if key not in self._training_status_cache:
            result = _safe_get(self._client.get_training_status, key)
            self._training_status_cache[key] = result or {}
        return self._training_status_cache[key]

    # ------------------------------------------------------------------
    # Individual metric fetchers
    # ------------------------------------------------------------------

    def fetch_stats(self, start: datetime.date, end: datetime.date) -> dict:
        """Average daily steps, active/intensity minutes, calories, floors, distance."""
        steps_list, active_list, intensity_list = [], [], []
        calories_list, floors_list, distance_list = [], [], []
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
            if data.get("totalKilocalories") is not None:
                calories_list.append(data["totalKilocalories"])
            if data.get("floorsAscended") is not None:
                floors_list.append(data["floorsAscended"])
            if data.get("totalDistanceMeters") is not None:
                distance_list.append(data["totalDistanceMeters"])

        return {
            "avg_daily_steps": int(sum(steps_list) / len(steps_list)) if steps_list else None,
            "avg_active_minutes": int(sum(active_list) / len(active_list)) if active_list else None,
            "avg_intensity_minutes": int(sum(intensity_list) / len(intensity_list)) if intensity_list else None,
            "avg_total_calories": int(sum(calories_list) / len(calories_list)) if calories_list else None,
            "avg_floors": round(sum(floors_list) / len(floors_list), 1) if floors_list else None,
            "avg_distance_km": round(sum(distance_list) / len(distance_list) / 1000, 2) if distance_list else None,
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
            if total_sec == 0:
                continue  # night not tracked — exclude from averages and nightly breakdown
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

        charged_vals = [d["charged"] for d in daily if d["charged"] is not None]
        drained_vals = [d["drained"] for d in daily if d["drained"] is not None]
        avg_max = round(sum(charged_vals) / len(charged_vals), 1) if charged_vals else None
        avg_min = round(sum(drained_vals) / len(drained_vals), 1) if drained_vals else None
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

    def fetch_training_load(self, end: datetime.date) -> dict:
        """Training load and status from the most-recent training status endpoint.

        Bug fix: the old per-day loop used wrong field names that never existed
        in the API response. The correct structure uses mostRecentTrainingStatus
        and mostRecentTrainingLoadBalance, which always reflect the latest data
        regardless of the date parameter passed.
        """
        data = self._get_training_status(end)
        if not data:
            return {
                "status_phrase": None, "acute_load": None, "chronic_load": None,
                "acwr_ratio": None, "acwr_status": None,
                "balance_phrase": None, "aerobic_low": None, "aerobic_high": None,
                "anaerobic": None,
            }

        # Training status: status phrase and acute/chronic load
        status_map = (data.get("mostRecentTrainingStatus") or {}).get("latestTrainingStatusData") or {}
        status_dto = _get_primary_data(status_map)
        status_phrase = _clean_phrase(status_dto.get("trainingStatusFeedbackPhrase"))
        acute_dto = status_dto.get("acuteTrainingLoadDTO") or {}
        acute_load = acute_dto.get("dailyTrainingLoadAcute")
        chronic_load = acute_dto.get("dailyTrainingLoadChronic")
        acwr_ratio = acute_dto.get("dailyAcuteChronicWorkloadRatio")
        acwr_status = _clean_phrase(acute_dto.get("acwrStatus"))

        # Load balance: aerobic/anaerobic breakdown
        balance_map = (data.get("mostRecentTrainingLoadBalance") or {}).get("metricsTrainingLoadBalanceDTOMap") or {}
        balance_dto = _get_primary_data(balance_map)
        balance_phrase = _clean_phrase(balance_dto.get("trainingBalanceFeedbackPhrase"))
        aerobic_low = balance_dto.get("monthlyLoadAerobicLow")
        aerobic_high = balance_dto.get("monthlyLoadAerobicHigh")
        anaerobic = balance_dto.get("monthlyLoadAnaerobic")

        return {
            "status_phrase": status_phrase,
            "acute_load": round(acute_load) if acute_load is not None else None,
            "chronic_load": round(chronic_load) if chronic_load is not None else None,
            "acwr_ratio": round(acwr_ratio, 2) if acwr_ratio is not None else None,
            "acwr_status": acwr_status,
            "balance_phrase": balance_phrase,
            "aerobic_low": round(aerobic_low) if aerobic_low is not None else None,
            "aerobic_high": round(aerobic_high) if aerobic_high is not None else None,
            "anaerobic": round(anaerobic) if anaerobic is not None else None,
        }

    def fetch_spo2(self, start: datetime.date, end: datetime.date) -> dict:
        """Average SpO2 (blood oxygen saturation) over the period."""
        daily = []
        for day in _date_range(start, end):
            data = _safe_get(self._client.get_spo2_data, day.strftime(DATE_FORMAT))
            if not data:
                continue
            avg = data.get("averageSpO2") or data.get("avgSpO2")
            lowest = data.get("lowestSpO2") or data.get("minSpO2")
            if avg:
                daily.append({"date": day.strftime(DATE_FORMAT), "avg_spo2": avg, "lowest_spo2": lowest})

        avg_vals = [d["avg_spo2"] for d in daily if d["avg_spo2"] is not None]
        low_vals = [d["lowest_spo2"] for d in daily if d.get("lowest_spo2") is not None]
        return {
            "daily": daily,
            "avg_spo2": round(sum(avg_vals) / len(avg_vals), 1) if avg_vals else None,
            "avg_lowest_spo2": round(sum(low_vals) / len(low_vals), 1) if low_vals else None,
        }

    def fetch_respiration(self, start: datetime.date, end: datetime.date) -> dict:
        """Average breathing rate (breaths/min) over the period."""
        daily = []
        for day in _date_range(start, end):
            data = _safe_get(self._client.get_respiration_data, day.strftime(DATE_FORMAT))
            if not data:
                continue
            waking = data.get("avgWakingRespirationValue") or data.get("startingRespirationValue")
            sleeping = data.get("avgSleepRespirationValue")
            if waking:
                daily.append({"date": day.strftime(DATE_FORMAT), "waking_brpm": waking, "sleep_brpm": sleeping})

        waking_vals = [d["waking_brpm"] for d in daily if d["waking_brpm"] is not None]
        sleep_vals = [d["sleep_brpm"] for d in daily if d.get("sleep_brpm") is not None]
        return {
            "daily": daily,
            "avg_waking_brpm": round(sum(waking_vals) / len(waking_vals), 1) if waking_vals else None,
            "avg_sleep_brpm": round(sum(sleep_vals) / len(sleep_vals), 1) if sleep_vals else None,
        }

    def fetch_training_readiness(self, start: datetime.date, end: datetime.date) -> dict:
        """Daily training readiness scores."""
        daily = []
        for day in _date_range(start, end):
            data = _safe_get(self._client.get_training_readiness, day.strftime(DATE_FORMAT))
            if not data:
                continue
            if isinstance(data, list):
                data = data[0] if data else {}
            score = data.get("score")
            level = data.get("level") or data.get("feedbackShort")
            if score is not None:
                daily.append({"date": day.strftime(DATE_FORMAT), "score": score, "level": level})

        scores = [d["score"] for d in daily if d["score"] is not None]
        return {
            "daily": daily,
            "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
            "latest_score": daily[-1]["score"] if daily else None,
            "latest_level": daily[-1].get("level") if daily else None,
        }

    def fetch_vo2max(self, end: datetime.date) -> dict:
        """Latest VO2 max from training status.

        Bug fix: get_max_metrics returns empty for this account. The training
        status endpoint reliably includes mostRecentVO2Max regardless of date.
        """
        data = self._get_training_status(end)
        if not data:
            return {"vo2_max": None}
        generic = (data.get("mostRecentVO2Max") or {}).get("generic") or {}
        return {
            "vo2_max": generic.get("vo2MaxPreciseValue") or generic.get("vo2MaxValue"),
        }

    def fetch_body_composition(self, start: datetime.date, end: datetime.date) -> dict:
        """Weight and body composition data for the period."""
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
                "bmi": entry.get("bmi"),
                "body_fat_pct": entry.get("bodyFatPercentage"),
            })

        entries.sort(key=lambda e: e["date"])
        weights = [e["weight_kg"] for e in entries]
        return {
            "entries": entries,
            "latest_weight_kg": entries[-1]["weight_kg"] if entries else None,
            "avg_weight_kg": round(sum(weights) / len(weights), 1) if weights else None,
            "latest_bmi": entries[-1].get("bmi") if entries else None,
            "latest_body_fat_pct": entries[-1].get("body_fat_pct") if entries else None,
        }

    def fetch_runs(self, start: datetime.date, end: datetime.date) -> dict:
        """Running activities with per-run HR zones and running dynamics."""
        data = _safe_get(
            self._client.get_activities_by_date,
            start.strftime(DATE_FORMAT),
            end.strftime(DATE_FORMAT),
            "running",
        )
        if not data:
            return {"runs": [], "run_count": 0, "total_distance_km": 0.0, "avg_pace_min_km": None}

        runs = []
        for activity in data:
            distance_m = activity.get("distance") or 0
            duration_s = activity.get("duration") or 0
            date = (activity.get("startTimeLocal") or "")[:10]
            activity_id = activity.get("activityId")

            distance_km = round(distance_m / 1000, 2)
            duration_min = round(duration_s / 60, 1)
            pace = round(duration_min / distance_km, 2) if distance_km > 0 else None

            # Enrich with running dynamics from per-km splits
            running_dynamics = {}
            hr_zones = {}

            if activity_id:
                splits_data = _safe_get(self._client.get_activity_splits, activity_id)
                if splits_data:
                    laps = splits_data.get("lapDTOs") or []
                    if laps:
                        def _lap_avg(key, _laps=laps):
                            vals = [l[key] for l in _laps if l.get(key) is not None]
                            return round(sum(vals) / len(vals), 1) if vals else None

                        cadence = _lap_avg("averageRunCadence")
                        power = _lap_avg("averagePower")
                        gct = _lap_avg("groundContactTime")
                        vo = _lap_avg("verticalOscillation")
                        running_dynamics = {
                            "avg_cadence_spm": round(cadence) if cadence else None,
                            "avg_power_w": round(power) if power else None,
                            "avg_ground_contact_ms": round(gct) if gct else None,
                            "avg_vertical_oscillation_cm": vo,
                        }

                zones_data = _safe_get(self._client.get_activity_hr_in_timezones, activity_id)
                if zones_data and isinstance(zones_data, list):
                    total_secs = sum(z.get("secsInZone", 0) for z in zones_data)
                    if total_secs > 0:
                        hr_zones = {
                            f"zone{z['zoneNumber']}_pct": round(z.get("secsInZone", 0) / total_secs * 100, 1)
                            for z in zones_data if z.get("zoneNumber")
                        }

            runs.append({
                "date": date,
                "distance_km": distance_km,
                "duration_min": duration_min,
                "avg_pace_min_km": pace,
                "avg_hr": activity.get("averageHR"),
                "activity_id": activity_id,
                "running_dynamics": running_dynamics,
                "hr_zones": hr_zones,
            })

        paces = [r["avg_pace_min_km"] for r in runs if r["avg_pace_min_km"]]
        return {
            "runs": sorted(runs, key=lambda r: r["date"]),
            "run_count": len(runs),
            "total_distance_km": round(sum(r["distance_km"] for r in runs), 2),
            "avg_pace_min_km": round(sum(paces) / len(paces), 2) if paces else None,
        }

    # ------------------------------------------------------------------
    # New fetchers (Stage 5A)
    # ------------------------------------------------------------------

    def fetch_race_predictions(self) -> dict:
        """Predicted race finish times from Garmin's race predictor model."""
        data = _safe_get(self._client.get_race_predictions)
        if not data:
            return {"time_5k": None, "time_10k": None, "time_half": None, "time_marathon": None}
        return {
            "time_5k": _fmt_duration(data.get("time5K")),
            "time_10k": _fmt_duration(data.get("time10K")),
            "time_half": _fmt_duration(data.get("timeHalfMarathon")),
            "time_marathon": _fmt_duration(data.get("timeMarathon")),
        }

    def fetch_endurance_score(self, start: datetime.date, end: datetime.date) -> dict:
        """Garmin endurance score with classification label."""
        data = _safe_get(
            self._client.get_endurance_score,
            start.strftime(DATE_FORMAT),
            end.strftime(DATE_FORMAT),
        )
        if not data:
            return {"score": None, "classification": None}

        dto = data.get("enduranceScoreDTO") or {}
        score = dto.get("overallScore")

        # Derive classification label from the thresholds in the response
        thresholds = [
            (dto.get("classificationLowerLimitElite", 8800), "Elite"),
            (dto.get("classificationLowerLimitSuperior", 8100), "Superior"),
            (dto.get("classificationLowerLimitExpert", 7300), "Expert"),
            (dto.get("classificationLowerLimitWellTrained", 6600), "Well-Trained"),
            (dto.get("classificationLowerLimitTrained", 5800), "Trained"),
            (dto.get("classificationLowerLimitIntermediate", 5100), "Intermediate"),
            (0, "Basic"),
        ]
        classification = "Unknown"
        if score is not None:
            for threshold, label in thresholds:
                if score >= threshold:
                    classification = label
                    break

        return {"score": score, "classification": classification}

    def fetch_weekly_intensity(self, start: datetime.date, end: datetime.date) -> dict:
        """Weekly intensity minutes (moderate + vigorous) vs WHO 150-min goal."""
        data = _safe_get(self._client.get_weekly_intensity_minutes, start.strftime(DATE_FORMAT), end.strftime(DATE_FORMAT))
        if not data or not isinstance(data, list):
            return {"weeks": []}

        weeks = []
        for entry in data:
            moderate = entry.get("moderateValue") or 0
            vigorous = entry.get("vigorousValue") or 0
            goal = entry.get("weeklyGoal") or 150
            # WHO counts vigorous double toward the 150-min moderate equivalent target
            total_equivalent = moderate + vigorous * 2
            weeks.append({
                "week_start": entry.get("calendarDate"),
                "moderate_min": moderate,
                "vigorous_min": vigorous,
                "goal_min": goal,
                "total_equivalent_min": total_equivalent,
                "met_goal": total_equivalent >= goal,
            })
        return {"weeks": weeks}

    def fetch_sweat_loss(self, start: datetime.date, end: datetime.date) -> dict:
        """Daily sweat loss (mL) estimated by Garmin from activity data."""
        daily = []
        for day in _date_range(start, end):
            data = _safe_get(self._client.get_hydration_data, day.strftime(DATE_FORMAT))
            if not data:
                continue
            sweat = data.get("sweatLossInML")
            if sweat and sweat > 0:
                daily.append({"date": day.strftime(DATE_FORMAT), "sweat_loss_ml": round(sweat)})

        avg = round(sum(d["sweat_loss_ml"] for d in daily) / len(daily)) if daily else None
        return {"daily": daily, "avg_sweat_loss_ml": avg}

    def fetch_hill_score(self, start: datetime.date, end: datetime.date) -> dict:
        """Garmin Hill Score — strength, endurance, and overall climbing ability."""
        data = _safe_get(
            self._client.get_hill_score,
            start.strftime(DATE_FORMAT),
            end.strftime(DATE_FORMAT),
        )
        if not data:
            return {"overall_score": None, "strength_score": None, "endurance_score": None}

        # Use the latest DTO entry (most recent)
        dtos = data.get("hillScoreDTOList") or []
        latest = dtos[0] if dtos else {}
        return {
            "overall_score": latest.get("overallScore"),
            "strength_score": latest.get("strengthScore"),
            "endurance_score": latest.get("enduranceScore"),
        }

    def fetch_morning_readiness(self, start: datetime.date, end: datetime.date) -> dict:
        """Morning training readiness measured post-sleep each day."""
        daily = []
        for day in _date_range(start, end):
            # Morning readiness is recorded for the previous night — use day-1
            data = _safe_get(
                self._client.get_morning_training_readiness,
                day.strftime(DATE_FORMAT),
            )
            if not data or not data.get("score"):
                continue
            daily.append({
                "date": data.get("calendarDate") or day.strftime(DATE_FORMAT),
                "score": data.get("score"),
                "level": data.get("level"),
                "sleep_score": data.get("sleepScore"),
                "recovery_time_h": data.get("recoveryTime"),
                "hrv_factor_pct": data.get("hrvFactorPercent"),
                "acute_load": data.get("acuteLoad"),
            })

        scores = [d["score"] for d in daily if d["score"] is not None]
        return {
            "daily": daily,
            "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
            "latest_score": daily[-1]["score"] if daily else None,
            "latest_level": daily[-1].get("level") if daily else None,
        }

    def fetch_fitness_age(self, end: datetime.date) -> dict:
        """Fitness age with contributing components."""
        data = _safe_get(self._client.get_fitnessage_data, end.strftime(DATE_FORMAT))
        if not data:
            return {"fitness_age": None, "achievable_fitness_age": None, "chronological_age": None}

        components = data.get("components") or {}
        rhr = (components.get("rhr") or {}).get("value")
        bmi = (components.get("bmi") or {}).get("value")
        vigorous_days = (components.get("vigorousDaysAvg") or {}).get("value")
        vigorous_min = (components.get("vigorousMinutesAvg") or {}).get("value")

        return {
            "fitness_age": data.get("fitnessAge"),
            "achievable_fitness_age": data.get("achievableFitnessAge"),
            "chronological_age": data.get("chronologicalAge"),
            "rhr_component": rhr,
            "bmi_component": bmi,
            "vigorous_days_avg": vigorous_days,
            "vigorous_min_avg": vigorous_min,
        }

    def fetch_lactate_threshold(self) -> dict:
        """Lactate threshold heart rate and running FTP power."""
        data = _safe_get(self._client.get_lactate_threshold)
        if not data:
            return {"lt_heart_rate": None, "ftp_watts": None}

        shr = data.get("speed_and_heart_rate") or {}
        power = data.get("power") or {}
        return {
            "lt_heart_rate": shr.get("heartRate"),
            "ftp_watts": power.get("functionalThresholdPower"),
        }

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
            "training_load": self.fetch_training_load(end),
            "runs": self.fetch_runs(start, end),
            "spo2": self.fetch_spo2(start, end),
            "respiration": self.fetch_respiration(start, end),
            "training_readiness": self.fetch_training_readiness(start, end),
            "vo2max": self.fetch_vo2max(end),
            "body_composition": self.fetch_body_composition(start, end),
            # New in Stage 5A
            "race_predictions": self.fetch_race_predictions(),
            "endurance_score": self.fetch_endurance_score(start, end),
            "weekly_intensity": self.fetch_weekly_intensity(start, end),
            "sweat_loss": self.fetch_sweat_loss(start, end),
            "hill_score": self.fetch_hill_score(start, end),
            "morning_readiness": self.fetch_morning_readiness(start, end),
            "fitness_age": self.fetch_fitness_age(end),
            "lactate_threshold": self.fetch_lactate_threshold(),
        }
