#!/usr/bin/env python3
"""Entry point for the AIFitnessSummary Health & Performance Digest System.

Usage:
    python main.py --cadence weekly
    python main.py --cadence block_checkin
    python main.py --cadence end_of_programme
    python main.py --cadence auto          # auto-detect from training plan
"""
import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env before importing modules that read env vars at import time
load_dotenv()

from aggregator import aggregate_weekly, aggregate_block_checkin, detect_escalation_flags
from claude_analyzer import ClaudeAnalyzer
from config import DATE_FORMAT, VALID_PERIODS, get_date_range
from email_client import get_email_client
from garmin_client import GarminClient
from hevy_client import HevyClient
from nutrition_client import get_nutrition_client
from plan_client import get_plan
from report_generator import ReportGenerator


def run_review(cadence: str) -> Path:
    """Fetch data, aggregate, generate AI analysis, write report, return path."""

    # 1. Load training plan
    plan = get_plan()
    if not plan:
        print("Warning: No training plan found. Running without plan context.", file=sys.stderr)

    # 2. Auto-detect cadence from plan if requested
    if cadence == "auto":
        if plan:
            cadence = plan.get_cadence_type()
            print(f"Auto-detected cadence: {cadence}")
        else:
            cadence = "weekly"
            print("No plan available for auto-detection, defaulting to weekly.")

    if cadence not in VALID_PERIODS:
        raise ValueError(f"Invalid cadence {cadence!r}. Choose from: {VALID_PERIODS}")

    # 3. Calculate date range
    start_date, end_date = get_date_range(cadence)

    cadence_label = cadence.replace("_", " ").title()
    print(f"\n=== {cadence_label} ===")
    print(f"Period: {start_date.strftime(DATE_FORMAT)} to {end_date.strftime(DATE_FORMAT)}\n")

    # 4. Get plan context for prompt
    plan_context = ""
    plan_targets = {}
    if plan:
        plan_context = plan.get_plan_context_for_prompt(end_date)
        block = plan.get_current_block(end_date)
        block_type = block["type"] if block else None
        plan_targets = {
            "volume_targets": plan.get_volume_targets(block_type),
            "planned_weekly_km": plan.get_planned_weekly_km(),
            "planned_sessions": plan.get_planned_sessions_per_week(),
            "planned_runs": plan.get_planned_runs_per_week(),
        }

    # 5. Fetch Garmin data
    garmin_data = {}
    try:
        garmin = GarminClient()
        garmin_data = garmin.collect_all(start_date, end_date)
    except Exception as e:
        print(f"Warning: Could not fetch Garmin data: {e}", file=sys.stderr)

    # 6. Fetch Hevy data
    hevy_summary = {}
    try:
        hevy = HevyClient()
        hevy_workouts = hevy.fetch_workouts(start_date, end_date)
        print(f"Fetched {len(hevy_workouts)} Hevy workouts.")
        template_lookup = hevy.fetch_exercise_templates()
        primary_lifts = plan.primary_lifts if plan else None
        hevy_summary = hevy.summarise_workouts(
            hevy_workouts,
            period_days=(end_date - start_date).days + 1,
            template_lookup=template_lookup,
            primary_lifts=primary_lifts,
        )
    except Exception as e:
        print(f"Warning: Could not fetch Hevy data: {e}", file=sys.stderr)

    # 7. Fetch nutrition data
    nutrition_data = None
    nutri_client = get_nutrition_client()
    if nutri_client:
        try:
            nutrition_data = nutri_client.fetch_data(start_date, end_date)
            days = nutrition_data.get("nutrition", {}).get("days_logged", 0)
            if days:
                print(f"Fetched {days} days of nutrition data.")
        except Exception as e:
            print(f"Warning: Could not fetch nutrition data: {e}", file=sys.stderr)

    # 8. Aggregate data
    if cadence in ("block_checkin", "end_of_programme"):
        summary = aggregate_block_checkin(
            garmin_data, hevy_summary, nutrition_data, plan_targets,
        )
    else:
        summary = aggregate_weekly(
            garmin_data, hevy_summary, nutrition_data, plan_targets,
        )

    # 9. Detect escalation flags
    escalation_flags = detect_escalation_flags(summary)
    if escalation_flags:
        print(f"Detected {len(escalation_flags)} escalation flag(s).")

    # 10. Generate Claude narrative
    analyzer = ClaudeAnalyzer()
    narrative = analyzer.generate_review(
        cadence=cadence,
        start_date=start_date.strftime(DATE_FORMAT),
        end_date=end_date.strftime(DATE_FORMAT),
        summary=summary,
        plan_context=plan_context,
        escalation_flags=escalation_flags,
    )

    # 11. Generate report
    report_path = ReportGenerator().generate(
        cadence=cadence,
        start_date=start_date,
        end_date=end_date,
        summary=summary,
        claude_narrative=narrative,
        plan_context=plan_context,
        escalation_flags=escalation_flags,
    )

    # 12. Send email
    email = get_email_client()
    if email:
        try:
            report_content = Path(report_path).read_text()
            email.send_report(cadence, str(end_date), report_content)
            print(f"Email sent to {os.getenv('EMAIL_RECIPIENT', 'configured recipient')}")
        except Exception as e:
            print(f"Warning: Email failed: {e}", file=sys.stderr)

    print(f"\nReport saved to: {report_path.resolve()}")
    return report_path


# Keep the old name as an alias so scheduler.py's call still works
run = run_review


def main():
    parser = argparse.ArgumentParser(
        description="Generate a Health & Performance Digest."
    )
    parser.add_argument(
        "--cadence",
        choices=list(VALID_PERIODS) + ["auto"],
        default="auto",
        help="Check-in type: weekly, block_checkin, end_of_programme, or auto (detect from plan)",
    )
    # Legacy support for --period
    parser.add_argument(
        "--period",
        choices=["weekly"],
        help="(Legacy) Alias for --cadence weekly",
    )
    args = parser.parse_args()

    cadence = args.cadence
    if args.period:
        cadence = args.period

    try:
        run_review(cadence)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
    except Exception as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
