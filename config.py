import datetime
import os
from pathlib import Path

REPORT_DIR = Path("reports")
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4096
DATE_FORMAT = "%Y-%m-%d"

WEEKLY_DAYS = 7
MONTHLY_DAYS = 30

VALID_PERIODS = ("weekly", "monthly")


DB_PATH = os.getenv("DB_PATH", str(Path(__file__).parent / "fitness_memory.db"))


def get_date_range(period: str) -> tuple[datetime.date, datetime.date]:
    """Return (start_date, end_date) for the given review period.

    end_date is yesterday (the last full day of data).
    """
    if period not in VALID_PERIODS:
        raise ValueError(f"period must be one of {VALID_PERIODS}, got {period!r}")

    end_date = datetime.date.today() - datetime.timedelta(days=1)
    days = WEEKLY_DAYS if period == "weekly" else MONTHLY_DAYS
    start_date = end_date - datetime.timedelta(days=days - 1)
    return start_date, end_date
