#!/usr/bin/env python3
"""Scheduler for the Health & Performance Digest System.

Triggers:
- Weekly Digest: Every Sunday evening (automated)
- Block Check-In: Sunday of programme-defined deload weeks (replaces weekly)
- End-of-Programme: Final week Sunday (replaces weekly)

Cadence is auto-detected from the training plan.

Two modes:
1. Daemon mode (default): Keeps running, triggering reviews on schedule.
       python scheduler.py
2. Install cron mode: Prints (or installs) crontab entries.
       python scheduler.py install-cron [--dry-run]
"""
import argparse
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import schedule

PROJECT_DIR = Path(__file__).parent.resolve()
PYTHON = sys.executable


def run_review(cadence: str = "auto") -> None:
    """Import and run main.run_review() in-process."""
    from dotenv import load_dotenv
    load_dotenv(PROJECT_DIR / ".env")

    import importlib
    main = importlib.import_module("main")
    try:
        main.run_review(cadence)
    except Exception as exc:
        print(f"[scheduler] Error during review: {exc}", file=sys.stderr)


def check_and_run_catchup():
    """On startup, check if a Sunday review was missed in the last 48 hours."""
    now = datetime.now()

    # Check if Sunday review was missed (Sunday = 6)
    days_since_sunday = (now.weekday() + 1) % 7  # 0=Sunday, 1=Mon, ...
    if 0 < days_since_sunday <= 2:  # Monday or Tuesday
        last_sunday = now - timedelta(days=days_since_sunday)
        scheduled = last_sunday.replace(hour=19, minute=0, second=0, microsecond=0)
        if now > scheduled and (now - scheduled) < timedelta(hours=48):
            print(f"Catch-up: running missed review (scheduled {scheduled})")
            run_review("auto")


def daemon() -> None:
    """Run the scheduler loop indefinitely."""
    check_and_run_catchup()

    # Sunday at 19:00 — cadence is auto-detected from plan
    schedule.every().sunday.at("19:00").do(run_review, cadence="auto")

    print("Scheduler started.")
    print("  Digest: every Sunday at 19:00 (cadence auto-detected from plan)")
    print("Press Ctrl+C to stop.\n")

    while True:
        schedule.run_pending()
        time.sleep(30)


# ------------------------------------------------------------------
# Cron management
# ------------------------------------------------------------------

CRON_SUNDAY = f"0 19 * * 0  cd {PROJECT_DIR} && {PYTHON} main.py --cadence auto >> {PROJECT_DIR}/reports/cron.log 2>&1"
CRON_MARKER = "# AIFitnessSummary"


def _current_crontab() -> str:
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else ""


def _install_cron(dry_run: bool = False) -> None:
    existing = _current_crontab()

    if CRON_MARKER in existing:
        print("AIFitnessSummary cron entries already present.")
        return

    new_entries = f"\n{CRON_MARKER}\n{CRON_SUNDAY}\n"
    updated = existing + new_entries

    print("Cron entry to be added:")
    print(CRON_SUNDAY)

    if dry_run:
        print("\n[dry-run] No changes made.")
        return

    proc = subprocess.run(["crontab", "-"], input=updated, text=True, capture_output=True)
    if proc.returncode == 0:
        print("\nCron entry installed successfully.")
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
        if skip and line.strip() and CRON_MARKER not in line and not line.startswith("0 19"):
            skip = False
        if not skip:
            filtered.append(line)
        elif line.strip() == "" and skip:
            skip = False

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

    sub.add_parser("daemon", help="Run the scheduler loop (default)")

    install_p = sub.add_parser("install-cron", help="Add crontab entry")
    install_p.add_argument("--dry-run", action="store_true")

    remove_p = sub.add_parser("remove-cron", help="Remove crontab entry")
    remove_p.add_argument("--dry-run", action="store_true")

    sub.add_parser("show-cron", help="Print the crontab entry")

    args = parser.parse_args()

    if args.command == "install-cron":
        _install_cron(dry_run=args.dry_run)
    elif args.command == "remove-cron":
        _remove_cron(dry_run=args.dry_run)
    elif args.command == "show-cron":
        print(CRON_SUNDAY)
    else:
        try:
            daemon()
        except KeyboardInterrupt:
            print("\nScheduler stopped.")


if __name__ == "__main__":
    main()
