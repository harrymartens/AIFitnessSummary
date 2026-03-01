#!/usr/bin/env python3
"""Entry point for the AIFitnessSummary review generator.

Usage:
    python main.py --period weekly
    python main.py --period monthly
"""
import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env before importing modules that read env vars at import time
load_dotenv()

from claude_analyzer import ClaudeAnalyzer
from config import DATE_FORMAT, VALID_PERIODS, get_date_range
from garmin_client import GarminClient
from hevy_client import HevyClient
from report_generator import ReportGenerator


def run(period: str) -> Path:
    """Fetch data, generate analysis, write report, return report path."""
    if period not in VALID_PERIODS:
        raise ValueError(f"Invalid period {period!r}. Choose from: {VALID_PERIODS}")

    start, end = get_date_range(period)
    print(f"\n=== {period.capitalize()} Fitness Review ===")
    print(f"Period: {start.strftime(DATE_FORMAT)} → {end.strftime(DATE_FORMAT)}\n")

    # 1. Fetch Garmin data
    garmin = GarminClient()
    garmin_data = garmin.collect_all(start, end)

    # 2. Fetch and summarise Hevy workouts
    hevy = HevyClient()
    period_days = (end - start).days + 1
    workouts = hevy.fetch_workouts(start, end)
    print(f"Fetched {len(workouts)} Hevy workouts.")
    hevy_summary = hevy.summarise_workouts(workouts, period_days=period_days)

    # 3. Generate Claude narrative
    analyzer = ClaudeAnalyzer()
    narrative = analyzer.generate_review(
        period=period,
        start_date=start.strftime(DATE_FORMAT),
        end_date=end.strftime(DATE_FORMAT),
        garmin_data=garmin_data,
        hevy_summary=hevy_summary,
    )

    # 4. Assemble and save the Markdown report
    generator = ReportGenerator()
    report_path = generator.generate(
        period=period,
        start_date=start,
        end_date=end,
        garmin_data=garmin_data,
        hevy_summary=hevy_summary,
        claude_narrative=narrative,
    )

    print(f"\nReport saved to: {report_path.resolve()}")
    return report_path


def main():
    parser = argparse.ArgumentParser(
        description="Generate a weekly or monthly AI fitness review."
    )
    parser.add_argument(
        "--period",
        choices=list(VALID_PERIODS),
        required=True,
        help="Review period: 'weekly' (last 7 days) or 'monthly' (last 30 days)",
    )
    args = parser.parse_args()

    try:
        run(args.period)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
    except Exception as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
