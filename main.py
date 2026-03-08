#!/usr/bin/env python3
"""Entry point for the AIFitnessSummary review generator.

Usage:
    python main.py --period weekly
    python main.py --period monthly
    python main.py goals
"""
import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env before importing modules that read env vars at import time
load_dotenv()

from claude_analyzer import ClaudeAnalyzer
from config import DATE_FORMAT, VALID_PERIODS, get_date_range
from db_client import get_db
from email_client import get_email_client
from garmin_client import GarminClient
from goal_manager import GoalManager
from applehealth_client import get_applehealth_client
from hevy_client import HevyClient
from knowledge_client import get_knowledge_context, get_research_context
from recommendation_tracker import RecommendationTracker
from report_generator import ReportGenerator
from trend_analyzer import TrendAnalyzer


def run_review(period: str) -> Path:
    """Fetch data, generate analysis, write report, return report path."""
    if period not in VALID_PERIODS:
        raise ValueError(f"Invalid period {period!r}. Choose from: {VALID_PERIODS}")

    # 1. Initialise shared resources
    db = get_db()

    # 2. Calculate date range
    start_date, end_date = get_date_range(period)

    print(f"\n=== {period.capitalize()} Fitness Review ===")
    print(f"Period: {start_date.strftime(DATE_FORMAT)} → {end_date.strftime(DATE_FORMAT)}\n")

    # 3. Load active goal (or infer provisional if none)
    gm = GoalManager(db, ClaudeAnalyzer())
    goal = gm.get_active_goal()
    # Note: provisional inference only happens interactively; skip in automated runs
    # If no goal, goal remains None — ClaudeAnalyzer handles the no-goal case gracefully

    # 4. Get historical trend context
    ta = TrendAnalyzer(db)
    trend_context = ta.get_trend_context(n=6)

    # 5. Get active recommendations for follow-up
    rt = RecommendationTracker(db)
    active_recs = rt.get_active_for_prompt()

    # 6. Fetch Garmin data
    garmin_data = {}
    try:
        garmin = GarminClient()
        garmin_data = garmin.collect_all(start_date, end_date)
    except Exception as e:
        print(f"Warning: Could not fetch Garmin data: {e}", file=sys.stderr)

    # 6b. Supplement body composition with Apple Health weight data (Eufy scale)
    ah = get_applehealth_client()
    if ah:
        try:
            ah_weight = ah.fetch_weight(start_date, end_date)
            if ah_weight.get("entries"):
                print(f"Fetched {len(ah_weight['entries'])} weight entries from Apple Health.")
                garmin_body = garmin_data.get("body_composition", {})
                if not garmin_body.get("latest_weight_kg"):
                    # No Garmin weight data — use Apple Health entirely
                    garmin_data["body_composition"] = {**garmin_body, **ah_weight}
                else:
                    # Merge: combine entries, prefer Apple Health for days where
                    # Garmin has no entry (scale data is typically more accurate)
                    garmin_dates = {e["date"] for e in garmin_body.get("entries", [])}
                    merged = list(garmin_body.get("entries", []))
                    for e in ah_weight["entries"]:
                        if e["date"] not in garmin_dates:
                            merged.append(e)
                    merged.sort(key=lambda e: e["date"])
                    weights = [e["weight_kg"] for e in merged]
                    garmin_data["body_composition"] = {
                        **garmin_body,
                        "entries": merged,
                        "latest_weight_kg": merged[-1]["weight_kg"] if merged else garmin_body.get("latest_weight_kg"),
                        "avg_weight_kg": round(sum(weights) / len(weights), 1) if weights else garmin_body.get("avg_weight_kg"),
                    }
        except Exception as e:
            print(f"Warning: Could not fetch Apple Health data: {e}", file=sys.stderr)

    # 7. Fetch Hevy data
    hevy_summary = {}
    try:
        hevy = HevyClient()
        hevy_workouts = hevy.fetch_workouts(start_date, end_date)
        print(f"Fetched {len(hevy_workouts)} Hevy workouts.")
        period_days = (end_date - start_date).days + 1
        template_lookup = hevy.fetch_exercise_templates()
        hevy_summary = hevy.summarise_workouts(
            hevy_workouts, period_days=period_days, template_lookup=template_lookup
        )
    except Exception as e:
        print(f"Warning: Could not fetch Hevy data: {e}", file=sys.stderr)

    # 8. Get knowledge and research context
    knowledge_ctx = ""
    research_ctx = ""
    try:
        knowledge_ctx = get_knowledge_context(garmin_data)
    except Exception as e:
        print(f"Warning: Could not load knowledge context: {e}", file=sys.stderr)
    try:
        research_ctx = get_research_context(garmin_data, goal)
    except Exception as e:
        print(f"Warning: Could not load research context: {e}", file=sys.stderr)
    combined_knowledge = "\n\n".join(filter(None, [knowledge_ctx, research_ctx]))

    # 9. Generate Claude narrative
    analyzer = ClaudeAnalyzer()
    narrative = analyzer.generate_review(
        period=period,
        start_date=start_date.strftime(DATE_FORMAT),
        end_date=end_date.strftime(DATE_FORMAT),
        garmin_data=garmin_data,
        hevy_summary=hevy_summary,
        goal=goal,
        trend_context=trend_context,
        active_recommendations=active_recs,
        knowledge_context=combined_knowledge or None,
    )

    # 10. Parse and store recommendations before stripping from narrative
    review_saved = False
    review_id = None
    followup_summary = ""
    try:
        review_id = ta.save_review(period, start_date, end_date, garmin_data, hevy_summary)
        rt.save_from_response(review_id, narrative)
        followup_result = rt.process_followup(narrative)
        followup_summary = rt.format_followup_summary(followup_result)
        review_saved = True
    except Exception as e:
        print(f"Warning: Could not save review to database: {e}", file=sys.stderr)

    # 11. Strip recommendations block from narrative before report
    clean_narrative = ClaudeAnalyzer.strip_recommendations_block(narrative)

    # 12. Generate Markdown report
    report_path = ReportGenerator().generate(
        period=period,
        start_date=start_date,
        end_date=end_date,
        garmin_data=garmin_data,
        hevy_summary=hevy_summary,
        claude_narrative=clean_narrative,
        goal=goal,
        trend_context_str=trend_context,
        followup_summary_str=followup_summary,
    )

    # 13. Update review with report path
    if review_saved and review_id is not None:
        try:
            db.update_review_report_path(review_id, str(report_path))
        except Exception:
            pass

    # 14. Send email
    email = get_email_client()
    if email:
        try:
            report_content = Path(report_path).read_text()
            email.send_report(period, str(end_date), report_content)
            print(f"Email sent to {os.getenv('EMAIL_RECIPIENT', 'configured recipient')}")
        except Exception as e:
            print(f"Warning: Email failed: {e}", file=sys.stderr)

    print(f"\nReport saved to: {report_path.resolve()}")
    return report_path


# Keep the old name as an alias so scheduler.py's `main.run(period)` call still works
run = run_review


def main():
    parser = argparse.ArgumentParser(
        description="Generate a weekly or monthly AI fitness review."
    )
    subparsers = parser.add_subparsers(dest='command')

    # 'goals' subcommand
    subparsers.add_parser('goals', help='Set up or update your fitness goals')

    parser.add_argument(
        "--period",
        choices=list(VALID_PERIODS),
        help="Review period: 'weekly' (last 7 days) or 'monthly' (last 30 days)",
    )
    args = parser.parse_args()

    if args.command == 'goals':
        gm = GoalManager(get_db(), ClaudeAnalyzer())
        gm.run_wizard()
        return

    # Default: generate fitness review
    if not args.period:
        parser.error("--period is required when not using a subcommand (e.g. --period weekly)")

    try:
        run_review(args.period)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
    except Exception as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
