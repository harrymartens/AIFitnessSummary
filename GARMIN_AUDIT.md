# Garmin API Audit — Stage 1C

**Date:** 2026-03-05
**Library version:** garminconnect 0.2.38
**Library file:** `/usr/local/lib/python3.11/dist-packages/garminconnect/__init__.py`
**Purpose:** Gap analysis of available vs currently collected metrics, to guide Stage 5A implementation.

---

## Section 1: Currently Collected Metrics

Every metric currently fetched by `garmin_client.py`, where it flows, and the API method used.

| Metric | API Method | garmin_client.py fetcher | Prompt | Report | Notes |
|--------|-----------|--------------------------|--------|--------|-------|
| Daily steps | `get_stats` (alias for `get_user_summary`) | `fetch_stats` | ✅ | ✅ | Averaged over period |
| Daily distance (km) | `get_stats` | `fetch_stats` | ✅ | ✅ | Converted from metres |
| Active minutes | `get_stats` | `fetch_stats` | ✅ | ✅ | moderate + vigorous×2 |
| Intensity minutes | `get_stats` | `fetch_stats` | ✅ | ✅ | moderate + vigorous (unweighted) |
| Floors ascended | `get_stats` | `fetch_stats` | ✅ | ✅ | Averaged over period |
| Total calories/day | `get_stats` | `fetch_stats` | ✅ | ✅ | totalKilocalories |
| Days with data | `get_stats` | `fetch_stats` | ❌ | ✅ | Appears in report table only |
| Resting heart rate (daily) | `get_heart_rates` | `fetch_heart_rates` | ✅ | ✅ | Daily trend + period average |
| HRV status (daily) | `get_hrv_data` | `fetch_hrv` | ✅ | ❌ | In prompt; no dedicated report table |
| HRV last-night avg ms | `get_hrv_data` | `fetch_hrv` | ✅ | ❌ | In prompt only |
| HRV weekly avg ms | `get_hrv_data` | `fetch_hrv` | ✅ | ✅ | Period average shown in cardio table |
| Sleep total hours | `get_sleep_data` | `fetch_sleep` | ✅ | ✅ | Nightly + averages |
| Sleep deep hours | `get_sleep_data` | `fetch_sleep` | ✅ | ✅ | |
| Sleep REM hours | `get_sleep_data` | `fetch_sleep` | ✅ | ✅ | |
| Sleep light hours | `get_sleep_data` | `fetch_sleep` | ✅ | ✅ | |
| Sleep awake hours | `get_sleep_data` | `fetch_sleep` | ✅ | ✅ | |
| Average stress level | `get_stress_data` | `fetch_stress` | ✅ | ✅ | avgStressLevel field; daily breakdown in prompt |
| Body battery charged | `get_body_battery` | `fetch_body_battery` | ✅ | ✅ | avg_max across period |
| Body battery drained | `get_body_battery` | `fetch_body_battery` | ✅ | ✅ | avg_min across period |
| Training load (daily) | `get_training_status` | `fetch_training_load` | ✅ | ✅ | Numeric load value |
| Training status label | `get_training_status` | `fetch_training_load` | ✅ | ✅ | Latest status string |
| SpO2 average | `get_spo2_data` | `fetch_spo2` | ✅ | ✅ | |
| SpO2 lowest | `get_spo2_data` | `fetch_spo2` | ✅ | ✅ | |
| Waking respiration rate | `get_respiration_data` | `fetch_respiration` | ✅ | ✅ | brpm |
| Sleep respiration rate | `get_respiration_data` | `fetch_respiration` | ✅ | ✅ | brpm |
| Training readiness score | `get_training_readiness` | `fetch_training_readiness` | ✅ | ✅ | Daily + avg + latest |
| Training readiness level | `get_training_readiness` | `fetch_training_readiness` | ✅ | ✅ | Feedback label |
| VO2 max | `get_max_metrics` | `fetch_vo2max` | ✅ | ✅ | Via generic.vo2MaxPreciseValue |
| Fitness age | `get_max_metrics` | `fetch_vo2max` | ✅ | ✅ | Via generic.fitnessAge |
| Weight (kg) | `get_body_composition` | `fetch_body_composition` | ✅ | ✅ | Latest + average |
| BMI | `get_body_composition` | `fetch_body_composition` | ✅ | ✅ | Latest only |
| Body fat % | `get_body_composition` | `fetch_body_composition` | ✅ | ✅ | Latest only |
| Muscle mass (kg) | `get_body_composition` | `fetch_body_composition` | ❌ | ❌ | Fetched but never surfaced (see Section 4) |
| Running distance (km) | `get_activities_by_date` | `fetch_runs` | ✅ | ✅ | Per run + total |
| Running duration (min) | `get_activities_by_date` | `fetch_runs` | ✅ | ✅ | |
| Running pace (min/km) | `get_activities_by_date` | `fetch_runs` | ✅ | ✅ | |
| Running avg HR | `get_activities_by_date` | `fetch_runs` | ✅ | ✅ | |

---

## Section 2: Available But Not Collected

Methods present in garminconnect 0.2.38 that `garmin_client.py` does NOT call, grouped by fitness value.

### High Priority

| Method | Returns | Special device/subscription? | Priority | Reason |
|--------|---------|------------------------------|----------|--------|
| `get_race_predictions()` | Predicted finish times for 5 K, 10 K, half-marathon, marathon | Requires running on GPS watch with sufficient training history | **High** | Directly actionable goal data for any runner; single API call, no date loop needed |
| `get_lactate_threshold()` | Running LT heart rate, LT speed (m/s), and FTP power (W) | Requires compatible running watch (e.g., Forerunner 965, Fenix 7) | **High** | LT pace and HR zone calibration are central to structured training; tells Claude where aerobic/anaerobic threshold sits |
| `get_hydration_data(cdate)` | Daily hydration logged (ml), goal (ml), sweat loss estimate | Requires manual logging or compatible scale/accessory | **High** | Hydration is a recovery and performance factor; easy to collect per-day in a loop |
| `get_all_day_stress(cdate)` | Intraday stress timeline (timestamped stress scores, rest vs active classification) | Standard Garmin wellness device | **High** | Richer than the single `avgStressLevel` already collected — shows peaks and troughs throughout the day |
| `get_weekly_intensity_minutes(start, end)` | Weekly moderate/vigorous intensity minutes vs weekly goal | Standard | **High** | WHO/AHA targets are weekly; the current system only shows daily averages. A week-by-week breakdown lets Claude spot under-training weeks |
| `get_personal_record()` | All-time running personal records (5 K, 10 K, half, marathon, etc.) | Requires GPS running history | **High** | Ground truth for performance benchmarking; complements race predictions |
| `get_endurance_score(startdate, enddate)` | Garmin's proprietary endurance score (daily or weekly aggregation) | Requires compatible watch | **High** | Single holistic cardio fitness metric that tracks improvement over months |

### Medium Priority

| Method | Returns | Special device/subscription? | Priority | Reason |
|--------|---------|------------------------------|----------|--------|
| `get_hill_score(startdate, enddate)` | Hill climbing score (Garmin proprietary metric) | Requires GPS watch with elevation | **Medium** | Useful for trail runners and cyclists; niche for flat-terrain users |
| `get_activity_hr_in_timezones(activity_id)` | Time spent in each HR zone per activity (zones 1–5) | Standard | **Medium** | Per-activity HR zone breakdown would let Claude evaluate training intensity distribution; requires iterating over activity IDs from existing `fetch_runs` |
| `get_activity_splits(activity_id)` | Lap/split data (pace, HR, cadence per km/mile) | Standard | **Medium** | Negative splits, consistency of pacing — high coaching value; requires activity-level loop |
| `get_activity_details(activity_id)` | Full telemetry: cadence, stride length, ground contact time, vertical oscillation, power (if available) | Some metrics require foot pod or advanced watch | **Medium** | Running dynamics metrics (cadence, ground contact, vertical oscillation) identify injury risk and efficiency |
| `get_floors(cdate)` | Intraday floors chart data (timestamped) | Standard | **Medium** | More granular than the floor count already in `get_stats`; useful for detecting NEAT patterns |
| `get_daily_steps(start, end)` | Range-query step data (steps per day in a batch) | Standard | **Medium** | The current code calls `get_stats` once per day. `get_daily_steps` fetches a date range in one call (up to 28 days), reducing API round-trips significantly |
| `get_weekly_steps(end, weeks)` | Weekly aggregate step counts | Standard | **Medium** | Trend view across multiple weeks — good for monthly/quarterly reports |
| `get_weekly_stress(end, weeks)` | Weekly stress aggregates | Standard | **Medium** | Same reasoning as weekly steps — longitudinal trend |
| `get_body_battery_events(cdate)` | Labelled events that charged or drained body battery (sleep, activities, stress) | Standard | **Medium** | Explains *why* battery went up or down; more insight than charged/drained totals |
| `get_progress_summary_between_dates(startdate, enddate, metric)` | Aggregated distance, duration, elevation per activity type over a period | Standard | **Medium** | Alternative to manually summing runs — includes cycling, hiking, etc. in one call |
| `get_morning_training_readiness(cdate)` | Post-sleep training readiness (AFTER_WAKEUP_RESET context) | Requires compatible watch with Morning Report | **Medium** | More actionable than the current all-day readiness score because it is specifically calibrated to the morning recovery state |
| `get_intensity_minutes_data(cdate)` | Daily intensity minutes detail (moderate/vigorous split) | Standard | **Medium** | The current `fetch_stats` already collects moderate + vigorous from the daily summary; this endpoint gives the same data with a dedicated call — only useful if `get_stats` is found to be missing these fields |
| `get_fitnessage_data(cdate)` | Garmin fitness age with contributing factors | Standard | **Medium** | Richer than the fitness age extracted from `get_max_metrics` — includes factor breakdown |

### Low Priority

| Method | Returns | Special device/subscription? | Priority | Reason |
|--------|---------|------------------------------|----------|--------|
| `get_devices()` | List of registered Garmin devices | N/A | **Low** | Useful once for context (device model) but not recurring fitness data |
| `get_primary_training_device()` | Primary training device details | N/A | **Low** | Same reasoning; one-time setup interest |
| `get_device_last_used()` | Last synced device | N/A | **Low** | Could detect sync gaps but marginal value |
| `get_blood_pressure(startdate, enddate)` | Logged blood pressure readings | Requires manual logging or compatible BP cuff | **Low** | Very user-specific; most users do not log BP via Garmin |
| `get_rhr_day(cdate)` | Resting HR via the stats service (metricId=60) | Standard | **Low** | `get_heart_rates` already returns `restingHeartRate` from the wellness service. `get_rhr_day` hits a different endpoint but returns equivalent data — redundant unless `get_heart_rates` returns None |
| `get_earned_badges()` | List of earned achievement badges | N/A | **Low** | No analytical fitness value |
| `get_available_badges()` | Badges not yet earned | N/A | **Low** | No analytical fitness value |
| `get_in_progress_badges()` | Badges partially completed | N/A | **Low** | No analytical fitness value |
| `get_adhoc_challenges()` | Historical ad-hoc challenges | N/A | **Low** | Gamification data; no fitness coaching value |
| `get_badge_challenges()` | Badge challenge history | N/A | **Low** | Same as above |
| `get_available_badge_challenges()` | Available badge challenges | N/A | **Low** | Same as above |
| `get_non_completed_badge_challenges()` | Incomplete badge challenges | N/A | **Low** | Same as above |
| `get_inprogress_virtual_challenges()` | In-progress virtual challenges | N/A | **Low** | Same as above |
| `get_goals()` | User-set goals (active/future/past) | N/A | **Low** | Could be interesting context but Garmin's goals feature is rarely used seriously |
| `get_gear()` | Registered shoes/equipment | N/A | **Low** | Shoe mileage tracking could matter for injury prevention; niche |
| `get_gear_stats()` | Distance/time logged per gear item | N/A | **Low** | Same — shoe retirement mileage is useful but low priority |
| `get_lifestyle_logging_data(cdate)` | Logged lifestyle events (alcohol, sleep notes, etc.) | Requires manual logging | **Low** | User-specific; most users do not log lifestyle data |
| `get_cycling_ftp()` | Cycling Functional Threshold Power | Requires power meter + compatible device | **Low** | Only relevant for cyclists with power meters |
| `get_menstrual_data_for_date()` | Menstrual cycle data | Requires explicit tracking | **Low** | User-specific; should only be included on explicit user request |
| `get_menstrual_calendar_data()` | Cycle history | Same as above | **Low** | Same as above |
| `get_pregnancy_summary()` | Pregnancy tracking snapshot | Requires explicit tracking | **Low** | Highly user-specific |
| `get_training_plans()` | Available training plans | N/A | **Low** | Meta-data, not performance data |
| `get_workouts()` | Planned workouts | N/A | **Low** | Planned vs executed could be valuable but requires significant added logic |
| `get_all_day_events(cdate)` | Auto-detected activities and events | Standard | **Low** | Mostly duplicates data available through activity endpoints; edge-case value for unrecorded activities |
| `get_user_summary(cdate)` | Full daily summary (superset of `get_stats`) | Standard | **Low** | `get_stats` already calls this; reviewing the full response might surface unused fields |
| `get_stats_and_body(cdate)` | Combined stats + body composition for a day | Standard | **Low** | Potentially replaces separate `get_stats` + `get_body_composition` calls; investigate as an optimisation |
| `get_activity_weather(activity_id)` | Weather conditions during an activity | Standard | **Low** | Interesting context but not actionable for most coaching |
| `get_activity_power_in_timezones(activity_id)` | Time in power zones per activity | Requires running power accessory | **Low** | Only relevant for users with running power meters |
| `get_device_solar_data()` | Solar charging data | Requires solar watch (Fenix Solar, Instinct Solar) | **Low** | Device-specific; not health data |
| `get_device_alarms()` | Active alarm list from all devices | N/A | **Low** | Not fitness data |
| `get_device_settings()` | Device configuration settings | N/A | **Low** | Not fitness data |
| `query_garmin_graphql()` | Flexible GraphQL queries | N/A | **Low** | Power-user escape hatch; no standard use-case defined |
| `count_activities()` | Total activity count | N/A | **Low** | Diagnostic utility only |
| `get_activity_types()` | Enumeration of all activity type keys | N/A | **Low** | Reference data; not per-session metric |

---

## Section 3: Metrics Currently Broken / Suspect

### 3.1 `fetch_training_load` — field name ambiguity

**Code:**
```python
load = data.get("trainingLoad")
status = data.get("trainingLoadStatus") or data.get("status")
```

**Issue:** The `get_training_status` endpoint returns a response shaped by the aggregated training-status service. The field key for the numeric load value is not reliably `trainingLoad` — in practice the field can be nested (e.g., inside a `trainingStatusDTO` or similar wrapper), and `trainingLoadStatus` is a key that has been observed to be absent in many device/firmware combinations. When both fields resolve to `None`, the entire day is silently skipped.

**Symptom:** `avg_load` and `latest_status` both `None` even when the user's watch shows a training status.

**Suggested fix:** Log the raw API response for one day and inspect all top-level keys. Add a fallback that walks common alternative paths (e.g., `data.get("latestMetrics", {}).get("trainingLoad")`).

---

### 3.2 `fetch_vo2max` — single-date fetch with list handling

**Code:**
```python
data = _safe_get(self._client.get_max_metrics, end.strftime(DATE_FORMAT))
if isinstance(data, list):
    data = data[0] if data else {}
generic = data.get("generic") or data
```

**Issue:** `get_max_metrics` is called for only the single `end` date and takes `cdate/cdate` as the range. If the user has not synced their device on that specific day (e.g., ran on `end - 1` but not `end`), the result will be empty or `None`, and VO2 max will silently read as `None` even though there is a perfectly valid measurement from the previous day.

**Symptom:** `vo2_max: None` shown in reports for periods where the user definitely has a VO2 max reading.

**Suggested fix:** Fall back to scanning the last 7 days when the single-day fetch returns empty; stop at the first non-null result.

---

### 3.3 `fetch_body_composition` — weight stored in grams, muscle mass not converted

**Code:**
```python
weight_g = entry.get("weight")
...
"weight_kg": round(weight_g / 1000, 1),
"muscle_mass_kg": entry.get("muscleMass"),  # raw value, unit unknown
```

**Issue:** `weight` from Garmin is reliably in grams and the `/1000` conversion is correct. However, `muscleMass` is fetched but its unit is not confirmed. Garmin may return it in grams (consistent with weight), kilograms, or as a percentage. Additionally, the field is never surfaced in the prompt or the report (see Section 4).

**Suggested fix:** Verify the `muscleMass` unit via a real API response and apply the same `/1000` conversion if needed. Then surface the value.

---

### 3.4 `fetch_stress` — negative stress scores silently excluded

**Code:**
```python
if avg and avg > 0:
    scores.append(avg)
```

**Issue:** Garmin uses -1 or -2 as sentinel values meaning "insufficient data" or "rest period." The `avg > 0` guard correctly excludes these. However, the truthiness check `if avg` also excludes a valid stress score of `0`. A score of exactly 0 would be silently dropped. In practice, 0 is an extremely rare value but the check is semantically wrong.

**Symptom:** No known user impact in practice; edge case.

**Suggested fix:** Change to `if avg is not None and avg > 0`.

---

### 3.5 `fetch_training_readiness` — list vs dict response handling is fragile

**Code:**
```python
if isinstance(data, list):
    data = data[0] if data else {}
score = data.get("score")
level = data.get("level") or data.get("feedbackShort")
```

**Issue:** The `get_training_readiness` endpoint can return a list (multiple readiness calculations for the day, e.g., morning + afternoon). The code takes only `data[0]` and discards any subsequent entries. It also looks for a `level` key, but the library's own `get_morning_training_readiness` shows the relevant key is `feedbackShort` or similar — there is no guarantee `level` exists, and `feedbackShort` is only a fallback.

**Symptom:** `latest_level` frequently returns `None` even when the Garmin app shows a readiness label.

**Suggested fix:** Use `get_morning_training_readiness` instead of raw `get_training_readiness`, which already implements the AFTER_WAKEUP_RESET filtering. Surface `feedbackShort` as the primary key for the label.

---

### 3.6 `_safe_get` — only retries on `GarminConnectTooManyRequestsError`, returns `None` on all other errors

**Code:**
```python
except GarminConnectTooManyRequestsError:
    ...
return None
```

**Issue:** The function returns `None` only if the retry loop falls through completely (impossible under current logic — the last retry re-raises). All other exceptions (network errors, `GarminConnectConnectionError`, `GarthHTTPError`) bubble up uncaught. The `return None` at the bottom is unreachable dead code. More critically, a transient network error on any single day will crash the entire run rather than skipping that day gracefully.

**Symptom:** Full script failure on intermittent connectivity issues.

**Suggested fix:** Add a broad `except Exception` catch-and-log in `_safe_get` so individual day failures are skipped gracefully; return `None` in that branch.

---

### 3.7 `fetch_sleep` — nightly sleep score not collected

**Issue:** The `get_sleep_data` response from Garmin includes a `sleepScores` sub-object (with an overall score, plus component scores for quality, duration, recovery). The current code reads only `dailySleepDTO` for the time breakdown and ignores the score entirely.

**Symptom:** The sleep score visible in the Garmin app is never included in the report or prompt.

**Suggested fix:** Extract `data.get("sleepScores", {}).get("overall")` (or equivalent key) alongside the existing sleep time fields.

---

## Section 4: Data Flow Gaps (Collected But Unused)

Metrics that `garmin_client.py` fetches and stores in the returned dict but which never appear in the Claude prompt or the report.

| Metric | Where stored in data dict | Why it is missing downstream |
|--------|--------------------------|------------------------------|
| `muscle_mass_kg` | `garmin_data["body_composition"]["entries"][n]["muscle_mass_kg"]` | `claude_analyzer.py` only formats `latest_weight_kg`, `avg_weight_kg`, `latest_bmi`, `latest_body_fat_pct`. `report_generator.py` mirrors the same four fields. `muscle_mass_kg` is fetched and put in `entries[]` but never read by either file. |
| HRV daily detail (status + last_night_avg_ms) | `garmin_data["hrv"]["daily"]` | The prompt includes this (`claude_analyzer.py` L63-64). The **report** has no dedicated HRV table — HRV is only in the cardio summary table as a single period-average value. The daily trend (analogous to the resting HR daily trend table) is absent from `report_generator.py`. |
| Body battery daily breakdown | `garmin_data["body_battery"]["daily"]` | Prompt does not iterate over daily body battery entries — only the period averages (`avg_max`, `avg_min`) are passed to Claude. `report_generator.py` likewise only shows the two averages. The full daily charged/drained trend is fetched but silently discarded. |
| Stress daily breakdown | `garmin_data["stress"]["daily"]` | The prompt does iterate over daily stress values (L106-107 in `claude_analyzer.py`). However, `report_generator.py` shows only the average stress level — there is no daily stress trend table in the report. |
| SpO2 daily breakdown | `garmin_data["spo2"]["daily"]` | `claude_analyzer.py` only surfaces period averages. The per-day SpO2 and lowest-SpO2 list in `daily` is never formatted into the prompt or report. |
| Respiration daily breakdown | `garmin_data["respiration"]["daily"]` | Same as SpO2 — only period averages reach the prompt/report; the day-by-day trend is discarded. |
| Training readiness daily detail | `garmin_data["training_readiness"]["daily"]` | The prompt iterates over daily readiness entries (L115-116 in `claude_analyzer.py`). The **report** only shows summary stats (avg score, latest score, latest level) — there is no daily readiness table in `report_generator.py`. |
| Run `duration_min` | `garmin_data["runs"]["runs"][n]["duration_min"]` | Present in the `runs` dict and shown in `report_generator._section_runs` table, but NOT included in the Claude prompt (`claude_analyzer.py` L148-150 formats only distance, pace, and optional HR — duration is omitted). |

---

## Section 5: Recommended Implementation Order

Top 10 new metrics ranked by coaching value, with implementation complexity.

| Rank | Metric | API Method(s) | Complexity | Rationale |
|------|--------|---------------|------------|-----------|
| 1 | **Race predictions** (5 K / 10 K / HM / marathon) | `get_race_predictions()` | Easy | Single call, no date loop. Directly actionable goal context for Claude. |
| 2 | **Hydration daily total** | `get_hydration_data(cdate)` | Easy | Same per-day loop pattern already used everywhere. Field: `totalIntakeInML` and `goalInML`. |
| 3 | **Intraday stress timeline** | `get_all_day_stress(cdate)` | Medium | Per-day fetch; response includes timestamped array. Useful derived metrics: peak stress time, rest-period duration. |
| 4 | **Weekly intensity minutes vs goal** | `get_weekly_intensity_minutes(start, end)` | Easy | Single range call returning weekly `moderateValue`, `vigorousValue`, `weeklyGoal`. Replaces the rough daily-average proxy currently used. |
| 5 | **Lactate threshold** | `get_lactate_threshold(latest=True)` | Easy | Single call (no date loop). Returns LT heart rate, LT pace, and FTP power. Essential for zone-based training analysis. |
| 6 | **All-time personal records** | `get_personal_record()` | Easy | Single call. Provides ground-truth PRs (5 K, 10 K, half, marathon) to anchor current-period performance commentary. |
| 7 | **Per-run HR zone breakdown** | `get_activity_hr_in_timezones(activity_id)` | Medium | Requires iterating over run activity IDs already returned by `fetch_runs`. Returns time in each of 5 zones per run. Enables training polarization analysis. |
| 8 | **Endurance score trend** | `get_endurance_score(start, end)` | Easy | Single range call with weekly aggregation. Garmin's holistic cardio fitness index — tracks long-term improvement better than single-day VO2 max. |
| 9 | **Sleep overall score** | `get_sleep_data(cdate)` — extract `sleepScores` | Easy | Already calling `get_sleep_data`; just add extraction of `sleepScores.overall` (or equivalent) from the existing response. Zero new API calls. |
| 10 | **Running lactate threshold pace/HR zones** + **per-run split data** | `get_activity_splits(activity_id)` | Medium | Lap-by-lap pace and HR — enables pacing consistency analysis. Requires activity-ID loop like item 7. |

---

## Section 6: Raw Method Inventory

Complete alphabetical list of all public methods in `garminconnect.Garmin` (v0.2.38), annotated with current-use status.

| Method | Currently used? |
|--------|----------------|
| `add_body_composition` | No (write method) |
| `add_gear_to_activity` | No (write method) |
| `add_hydration_data` | No (write method) |
| `add_weigh_in` | No (write method) |
| `add_weigh_in_with_timestamps` | No (write method) |
| `count_activities` | No |
| `create_manual_activity` | No (write method) |
| `create_manual_activity_from_json` | No (write method) |
| `delete_activity` | No (write method) |
| `delete_blood_pressure` | No (write method) |
| `delete_weigh_in` | No (write method) |
| `delete_weigh_ins` | No (write method) |
| `download` | No (internal helper) |
| `download_activity` | No |
| `download_workout` | No |
| `get_activities` | No |
| `get_activities_by_date` | **Yes** (`fetch_runs`) |
| `get_activities_fordate` | No |
| `get_activity` | No |
| `get_activity_details` | No |
| `get_activity_exercise_sets` | No |
| `get_activity_gear` | No |
| `get_activity_hr_in_timezones` | No |
| `get_activity_power_in_timezones` | No |
| `get_activity_split_summaries` | No |
| `get_activity_splits` | No |
| `get_activity_typed_splits` | No |
| `get_activity_types` | No |
| `get_activity_weather` | No |
| `get_adaptive_training_plan_by_id` | No |
| `get_adhoc_challenges` | No |
| `get_all_day_events` | No |
| `get_all_day_stress` | No |
| `get_available_badge_challenges` | No |
| `get_available_badges` | No |
| `get_badge_challenges` | No |
| `get_blood_pressure` | No |
| `get_body_battery` | **Yes** (`fetch_body_battery`) |
| `get_body_battery_events` | No |
| `get_body_composition` | **Yes** (`fetch_body_composition`) |
| `get_cycling_ftp` | No |
| `get_daily_steps` | No |
| `get_daily_weigh_ins` | No |
| `get_device_alarms` | No |
| `get_device_last_used` | No |
| `get_device_settings` | No |
| `get_device_solar_data` | No |
| `get_devices` | No |
| `get_earned_badges` | No |
| `get_endurance_score` | No |
| `get_fitnessage_data` | No |
| `get_floors` | No |
| `get_full_name` | No |
| `get_gear` | No |
| `get_gear_activities` | No |
| `get_gear_defaults` | No |
| `get_gear_stats` | No |
| `get_goals` | No |
| `get_heart_rates` | **Yes** (`fetch_heart_rates`) |
| `get_hill_score` | No |
| `get_hrv_data` | **Yes** (`fetch_hrv`) |
| `get_hydration_data` | No |
| `get_in_progress_badges` | No |
| `get_inprogress_virtual_challenges` | No |
| `get_intensity_minutes_data` | No |
| `get_lactate_threshold` | No |
| `get_last_activity` | No |
| `get_lifestyle_logging_data` | No |
| `get_max_metrics` | **Yes** (`fetch_vo2max`) |
| `get_menstrual_calendar_data` | No |
| `get_menstrual_data_for_date` | No |
| `get_morning_training_readiness` | No |
| `get_non_completed_badge_challenges` | No |
| `get_personal_record` | No |
| `get_pregnancy_summary` | No |
| `get_primary_training_device` | No |
| `get_progress_summary_between_dates` | No |
| `get_race_predictions` | No |
| `get_respiration_data` | **Yes** (`fetch_respiration`) |
| `get_rhr_day` | No |
| `get_scheduled_workout_by_id` | No |
| `get_sleep_data` | **Yes** (`fetch_sleep`) |
| `get_spo2_data` | **Yes** (`fetch_spo2`) |
| `get_stats` | **Yes** (`fetch_stats`) — alias for `get_user_summary` |
| `get_stats_and_body` | No |
| `get_steps_data` | No |
| `get_stress_data` | **Yes** (`fetch_stress`) |
| `get_training_plans` | No |
| `get_training_plan_by_id` | No |
| `get_training_readiness` | **Yes** (`fetch_training_readiness`) |
| `get_training_status` | **Yes** (`fetch_training_load`) |
| `get_unit_system` | No |
| `get_user_profile` | No |
| `get_user_summary` | No (called indirectly via `get_stats`) |
| `get_userprofile_settings` | No |
| `get_weigh_ins` | No |
| `get_weekly_intensity_minutes` | No |
| `get_weekly_steps` | No |
| `get_weekly_stress` | No |
| `get_workout_by_id` | No |
| `get_workouts` | No |
| `login` | **Yes** (authentication) |
| `logout` | No (deprecated) |
| `query_garmin_graphql` | No |
| `remove_gear_from_activity` | No (write method) |
| `request_reload` | No |
| `resume_login` | **Yes** (MFA flow) |
| `set_activity_name` | No (write method) |
| `set_activity_type` | No (write method) |
| `set_blood_pressure` | No (write method) |
| `set_gear_default` | No (write method) |
| `upload_activity` | No (write method) |
| `upload_cycling_workout` | No (write method) |
| `upload_hiking_workout` | No (write method) |
| `upload_running_workout` | No (write method) |
| `upload_swimming_workout` | No (write method) |
| `upload_walking_workout` | No (write method) |
| `upload_workout` | No (write method) |

**Summary:** 13 read methods currently used out of ~80 read methods available (write/upload/delete methods excluded from denominator). Approximately 67 read endpoints remain untapped.
