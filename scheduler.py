#!/usr/bin/env python3
"""Scheduler for automatic fitness reviews.

Two modes:

1. Daemon mode (default):
   Keeps running, triggering reviews on schedule.
       python scheduler.py

2. Install cron mode:
   Prints (or installs) crontab entries for the current Python interpreter.
       python scheduler.py --install-cron [--dry-run]
"""
import argparse
import datetime
import subprocess
import sys
import time
from pathlib import Path

import schedule

# Resolve paths so the cron entries work from any working directory
PROJECT_DIR = Path(__file__).parent.resolve()
PYTHON = sys.executable


def run_review(period: str) -> None:
    """Import and run main.run_review() in-process."""
    from dotenv import load_dotenv
    load_dotenv(PROJECT_DIR / ".env")

    # Re-import here so dotenv is loaded first
    import importlib
    main = importlib.import_module("main")
    try:
        main.run_review(period)
    except Exception as exc:
        print(f"[scheduler] Error during {period} review: {exc}", file=sys.stderr)


def check_and_run_catchup():
    """
    On scheduler startup, check if any scheduled review was missed in the
    last 24 hours. If so, run it immediately.

    Logic:
    - Weekly review due: last Monday at 07:00. If now is Tuesday–Wednesday and
      it's been < 48 hours since Monday 07:00, run a weekly review.
    - Monthly review due: 1st of month at 07:00. If now is 2nd–3rd and it's
      been < 48 hours since the 1st at 07:00, run a monthly review.
    """
    from datetime import datetime, timedelta
    now = datetime.now()

    # Check weekly catch-up (Monday = 0)
    days_since_monday = now.weekday()  # 0=Mon, 1=Tue, ...
    if 0 < days_since_monday <= 2:  # Tuesday or Wednesday
        last_monday = now - timedelta(days=days_since_monday)
        scheduled = last_monday.replace(hour=7, minute=0, second=0, microsecond=0)
        if now > scheduled and (now - scheduled) < timedelta(hours=48):
            print(f"Catch-up: running missed weekly review (scheduled {scheduled})")
            run_review("weekly")

    # Check monthly catch-up (1st of month)
    if 1 < now.day <= 3:
        scheduled = now.replace(day=1, hour=7, minute=0, second=0, microsecond=0)
        if now > scheduled and (now - scheduled) < timedelta(hours=48):
            print(f"Catch-up: running missed monthly review (scheduled {scheduled})")
            run_review("monthly")


def _monthly_check() -> None:
    """Only trigger monthly review on the 1st of the month."""
    if datetime.date.today().day == 1:
        run_review("monthly")


def daemon() -> None:
    """Run the scheduler loop indefinitely."""
    check_and_run_catchup()

    schedule.every().monday.at("07:00").do(run_review, period="weekly")
    schedule.every().day.at("07:00").do(_monthly_check)

    print("Scheduler started.")
    print("  Weekly review : every Monday at 07:00")
    print("  Monthly review: 1st of each month at 07:00")
    print("Press Ctrl+C to stop.\n")

    while True:
        schedule.run_pending()
        time.sleep(30)


# ------------------------------------------------------------------
# Cron management
# ------------------------------------------------------------------

CRON_WEEKLY = f"0 7 * * 1  cd {PROJECT_DIR} && {PYTHON} main.py --period weekly >> {PROJECT_DIR}/reports/cron.log 2>&1"
CRON_MONTHLY = f"0 7 1 * *  cd {PROJECT_DIR} && {PYTHON} main.py --period monthly >> {PROJECT_DIR}/reports/cron.log 2>&1"
CRON_MARKER = "# AIFitnessSummary"


def _current_crontab() -> str:
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    # `crontab -l` exits non-zero when there are no entries — that's fine
    return result.stdout if result.returncode == 0 else ""


def _install_cron(dry_run: bool = False) -> None:
    existing = _current_crontab()

    if CRON_MARKER in existing:
        print("AIFitnessSummary cron entries already present.")
        return

    new_entries = f"\n{CRON_MARKER}\n{CRON_WEEKLY}\n{CRON_MONTHLY}\n"
    updated = existing + new_entries

    print("Cron entries to be added:")
    print(CRON_WEEKLY)
    print(CRON_MONTHLY)

    if dry_run:
        print("\n[dry-run] No changes made.")
        return

    proc = subprocess.run(["crontab", "-"], input=updated, text=True, capture_output=True)
    if proc.returncode == 0:
        print("\nCron entries installed successfully.")
    else:
        print(f"\nFailed to install cron: {proc.stderr}", file=sys.stderr)
        sys.exit(1)


def _remove_cron(dry_run: bool = False) -> None:
    existing = _current_crontab()
    if CRON_MARKER not in existing:
        print("No AIFitnessSummary cron entries found.")
        return

    lines = existing.splitlines(keepends=True)
    filtered = []
    skip = False
    for line in lines:
        if CRON_MARKER in line:
            skip = True
        if skip and line.strip() and CRON_MARKER not in line and not line.startswith("0 7"):
            skip = False
        if not skip:
            filtered.append(line)
        elif line.strip() == "" and skip:
            skip = False  # blank line ends the block

    updated = "".join(filtered)

    if dry_run:
        print("[dry-run] Would remove AIFitnessSummary cron entries.")
        return

    subprocess.run(["crontab", "-"], input=updated, text=True)
    print("AIFitnessSummary cron entries removed.")


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="AIFitnessSummary scheduler")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("daemon", help="Run the in-process scheduler loop (default if no command given)")

    install_p = sub.add_parser("install-cron", help="Add crontab entries for weekly + monthly reviews")
    install_p.add_argument("--dry-run", action="store_true", help="Print what would be added without writing")

    remove_p = sub.add_parser("remove-cron", help="Remove AIFitnessSummary crontab entries")
    remove_p.add_argument("--dry-run", action="store_true")

    show_p = sub.add_parser("show-cron", help="Print the crontab entries that would be installed")

    args = parser.parse_args()

    if args.command == "install-cron":
        _install_cron(dry_run=args.dry_run)
    elif args.command == "remove-cron":
        _remove_cron(dry_run=args.dry_run)
    elif args.command == "show-cron":
        print(CRON_WEEKLY)
        print(CRON_MONTHLY)
    else:
        # Default: daemon
        try:
            daemon()
        except KeyboardInterrupt:
            print("\nScheduler stopped.")


if __name__ == "__main__":
    main()
