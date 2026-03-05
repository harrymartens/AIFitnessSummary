"""
Garmin API probe — tests each candidate endpoint and prints what data is returned.
Run with: GARMIN_EMAIL=... GARMIN_PASSWORD=... python _probe_garmin.py
"""
import datetime
import json
import os
import sys
from pathlib import Path

from garminconnect import Garmin, GarminConnectAuthenticationError

TOKENSTORE = os.path.expanduser("~/.garminconnect")
END = datetime.date.today()
START = END - datetime.timedelta(days=6)  # last 7 days
DATE_FMT = "%Y-%m-%d"


def login():
    # Try cached tokens first
    try:
        client = Garmin()
        client.login(TOKENSTORE)
        print("✓ Loaded from cached tokens\n")
        return client
    except Exception:
        pass

    email = os.environ.get("GARMIN_EMAIL", "")
    password = os.environ.get("GARMIN_PASSWORD", "")
    if not email or not password:
        sys.exit("Set GARMIN_EMAIL and GARMIN_PASSWORD env vars")

    print("Performing first-time login (may require MFA)…")
    client = Garmin(email=email, password=password, is_cn=False, return_on_mfa=True)
    result, mfa_data = client.login()
    if result == "needs_mfa":
        mfa_code = os.environ.get("GARMIN_MFA", "").strip()
        if not mfa_code:
            sys.exit(
                "\nGarmin sent a 6-digit verification code to your email.\n"
                "Re-run with: GARMIN_MFA=<code> python _probe_garmin.py"
            )
        client.resume_login(mfa_data, mfa_code)

    Path(TOKENSTORE).mkdir(mode=0o700, exist_ok=True)
    client.garth.dump(TOKENSTORE)
    print("✓ Tokens saved\n")
    return client


def probe(label, func, *args, show_keys=True, **kwargs):
    """Call func, print status + top-level keys or first item if list."""
    print(f"  [{label}]")
    try:
        result = func(*args, **kwargs)
        if result is None:
            print("    → None")
            return None
        if isinstance(result, list):
            if not result:
                print("    → empty list")
                return result
            print(f"    → list[{len(result)}], first item keys: {list(result[0].keys()) if isinstance(result[0], dict) else type(result[0]).__name__}")
            if len(result) <= 3:
                print(f"    → {json.dumps(result, default=str)[:500]}")
            else:
                print(f"    → {json.dumps(result[0], default=str)[:500]}")
        elif isinstance(result, dict):
            print(f"    → dict keys: {list(result.keys())}")
            print(f"    → {json.dumps(result, default=str)[:800]}")
        else:
            print(f"    → {result}")
        return result
    except Exception as e:
        print(f"    → ERROR: {type(e).__name__}: {e}")
        return None


def main():
    client = login()
    start_s = START.strftime(DATE_FMT)
    end_s = END.strftime(DATE_FMT)
    yesterday_s = (END - datetime.timedelta(days=1)).strftime(DATE_FMT)

    print(f"Probing endpoints for {start_s} → {end_s}\n")

    # ── BUG FIXES: inspect raw responses ──────────────────────────────────

    print("=== BUG FIX PROBES ===\n")

    print("1. fetch_training_load — raw response for one day:")
    probe("get_training_status", client.get_training_status, yesterday_s)

    print("\n2. fetch_vo2max — end date vs previous 7 days:")
    for i in range(7):
        d = (END - datetime.timedelta(days=i)).strftime(DATE_FMT)
        probe(f"get_max_metrics({d})", client.get_max_metrics, d)

    print("\n3. fetch_body_composition — muscle mass field:")
    probe("get_body_composition", client.get_body_composition, start_s, end_s)

    # ── NEW HIGH-PRIORITY ENDPOINTS ────────────────────────────────────────

    print("\n=== HIGH-PRIORITY NEW ENDPOINTS ===\n")

    probe("get_race_predictions", client.get_race_predictions)
    probe("get_personal_record", client.get_personal_record)
    probe("get_lactate_threshold", client.get_lactate_threshold)
    probe("get_endurance_score", client.get_endurance_score, start_s, end_s)

    print("\nHydration (last 7 days):")
    for i in range(7):
        d = (END - datetime.timedelta(days=i)).strftime(DATE_FMT)
        probe(f"get_hydration_data({d})", client.get_hydration_data, d)

    print("\nWeekly intensity minutes:")
    probe("get_weekly_intensity_minutes", client.get_weekly_intensity_minutes, start_s, end_s)

    # ── NEW MEDIUM-PRIORITY ENDPOINTS ─────────────────────────────────────

    print("\n=== MEDIUM-PRIORITY NEW ENDPOINTS ===\n")

    probe("get_hill_score", client.get_hill_score, start_s, end_s)
    probe("get_morning_training_readiness", client.get_morning_training_readiness, yesterday_s)
    probe("get_fitnessage_data", client.get_fitnessage_data, yesterday_s)
    probe("get_body_battery_events", client.get_body_battery_events, yesterday_s)

    print("\nWeekly stress:")
    probe("get_weekly_stress", client.get_weekly_stress, end_s, 4)

    print("\nWeekly steps:")
    probe("get_weekly_steps", client.get_weekly_steps, end_s, 4)

    print("\nActivity HR zones (need activity IDs from runs first):")
    runs = client.get_activities_by_date(start_s, end_s, "running")
    if runs:
        activity_id = runs[0].get("activityId")
        print(f"  Using activity_id={activity_id}")
        probe("get_activity_hr_in_timezones", client.get_activity_hr_in_timezones, activity_id)
        probe("get_activity_splits", client.get_activity_splits, activity_id)
        probe("get_activity_details", client.get_activity_details, activity_id)
    else:
        print("  No runs found in date range — skipping activity-level probes")

    print("\n=== DONE ===")


if __name__ == "__main__":
    main()
