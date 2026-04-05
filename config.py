import datetime
import os
from pathlib import Path

REPORT_DIR = Path("reports")
MODEL = "claude-sonnet-4-6"
DATE_FORMAT = "%Y-%m-%d"

# Token budgets per cadence (proposal Section 6.3)
WEEKLY_MAX_TOKENS = 1024    # 700-900 target, buffer for structure
BLOCK_MAX_TOKENS = 1800     # 1200-1500 target, buffer for structure
PROGRAMME_MAX_TOKENS = 1800

WEEKLY_DAYS = 7

VALID_PERIODS = ("weekly", "block_checkin", "end_of_programme")

DB_PATH = os.getenv("DB_PATH", str(Path(__file__).parent / "fitness_memory.db"))

TRAINING_PLAN_PATH = os.getenv(
    "TRAINING_PLAN_PATH",
    str(Path(__file__).parent / "training_plan.md"),
)


def get_max_tokens(period: str) -> int:
    """Return the appropriate token budget for the given cadence type."""
    if period == "block_checkin":
        return BLOCK_MAX_TOKENS
    if period == "end_of_programme":
        return PROGRAMME_MAX_TOKENS
    return WEEKLY_MAX_TOKENS


def get_date_range(period: str) -> tuple[datetime.date, datetime.date]:
    """Return (start_date, end_date) for the given review period.

    end_date is yesterday (the last full day of data).
    Weekly and block_checkin both cover 7 days.
    end_of_programme covers the final block period.
    """
    if period not in VALID_PERIODS:
        raise ValueError(f"period must be one of {VALID_PERIODS}, got {period!r}")

    end_date = datetime.date.today() - datetime.timedelta(days=1)

    if period == "end_of_programme":
        # For end-of-programme, try to cover the full final block
        try:
            from plan_client import get_plan
            plan = get_plan()
            if plan:
                block = plan.get_current_block(end_date)
                if block:
                    return block["start"], end_date
        except Exception:
            pass
        # Fallback: last 7 days
        start_date = end_date - datetime.timedelta(days=WEEKLY_DAYS - 1)
        return start_date, end_date

    # weekly and block_checkin both use 7-day windows
    start_date = end_date - datetime.timedelta(days=WEEKLY_DAYS - 1)
    return start_date, end_date
