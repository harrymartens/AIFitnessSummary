"""
recommendation_tracker.py

Manages the lifecycle of actionable recommendations across reviews.
Saves recommendations from Claude's structured output, retrieves active
ones for follow-up, and updates statuses based on Claude's assessment.
"""

from datetime import datetime, timezone
from typing import Optional

from db_client import DatabaseClient, get_db

_tracker_singleton: Optional["RecommendationTracker"] = None

# Priority constants (must match claude_analyzer.py)
PRIORITY_HIGH = 1
PRIORITY_MEDIUM = 2
PRIORITY_LOW = 3

PRIORITY_LABEL = {PRIORITY_HIGH: "HIGH", PRIORITY_MEDIUM: "MEDIUM", PRIORITY_LOW: "LOW"}

# Window (in characters) around recommendation text to search for status keywords
FOLLOWUP_WINDOW = 200


class RecommendationTracker:
    """Manages the full lifecycle of fitness recommendations across reviews."""

    def __init__(self, db: DatabaseClient) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save_from_response(self, review_id: int, claude_response: str) -> list[dict]:
        """
        Parse structured recommendations from Claude's response using
        ClaudeAnalyzer.parse_recommendations(), save each to DB,
        and return the list of saved recommendation dicts (with ids).

        Only saves recommendations where priority <= 2 (HIGH or MEDIUM)
        unless fewer than 2 are found, in which case saves all.
        """
        from claude_analyzer import ClaudeAnalyzer

        all_recs = ClaudeAnalyzer.parse_recommendations(claude_response)
        if not all_recs:
            return []

        # Filter to HIGH/MEDIUM only, but fall back to all if fewer than 2 qualify
        high_medium = [r for r in all_recs if r.get("priority", PRIORITY_MEDIUM) <= PRIORITY_MEDIUM]
        recs_to_save = high_medium if len(high_medium) >= 2 else all_recs

        self._db.save_recommendations(review_id, recs_to_save)

        # Re-query DB to get rows with their assigned ids and created_at
        all_active = self._db.get_active_recommendations()

        # Match by text to return only the newly-saved records
        saved_texts = {r["text"] for r in recs_to_save}
        saved = [r for r in all_active if r["text"] in saved_texts]
        return saved

    def get_active_for_prompt(self) -> list[dict]:
        """
        Retrieve all active recommendations from DB.
        Format each as a dict: {id, category, priority, text, created_at, age_days}
        Sorted by priority ASC (HIGH first), then created_at DESC.
        Returns [] if none.
        """
        raw = self._db.get_active_recommendations()
        if not raw:
            return []

        now = datetime.now(timezone.utc)
        result = []
        for rec in raw:
            created_at_str = rec.get("created_at", "")
            try:
                created_dt = datetime.fromisoformat(created_at_str)
                # Make aware if naive (DB stores UTC without tzinfo)
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=timezone.utc)
                age_days = (now - created_dt).days
            except (ValueError, TypeError):
                age_days = 0

            result.append(
                {
                    "id": rec["id"],
                    "category": rec["category"],
                    "priority": rec["priority"],
                    "text": rec["text"],
                    "created_at": created_at_str,
                    "age_days": age_days,
                }
            )

        # Sort: priority ASC (1=HIGH first), then created_at DESC (newest first).
        # Convert created_at to a timestamp and negate it so that a standard
        # ascending sort gives newest-first within each priority tier.
        def sort_key(rec: dict) -> tuple:
            try:
                ts = datetime.fromisoformat(rec["created_at"]).timestamp()
            except (ValueError, TypeError):
                ts = 0.0
            return (rec["priority"], -ts)

        result.sort(key=sort_key)
        return result

    def process_followup(self, claude_response: str) -> dict:
        """
        Parse Claude's assessment of previous recommendations from the response.

        Strategy:
        1. Get all active recommendations from DB.
        2. For each, search the Claude response for the recommendation text (or key words)
           and look for RESOLVED / CONTINUED / ESCALATED nearby (within ±200 chars).
        3. Update status accordingly:
           - RESOLVED  → status="resolved",  resolved_at=now
           - ESCALATED → status="escalated", resolution_note="Escalated in review {date}"
           - CONTINUED → no change (stays active)
        4. Return summary dict: {"resolved": [...], "escalated": [...], "continued": [...]}

        If no clear signal is found for a recommendation, leave it as active (CONTINUED).
        """
        active_recs = self._db.get_active_recommendations()

        resolved_list: list[dict] = []
        escalated_list: list[dict] = []
        continued_list: list[dict] = []

        today_str = datetime.now(timezone.utc).date().isoformat()

        for rec in active_recs:
            status = self._detect_followup_status(claude_response, rec["text"])

            if status == "RESOLVED":
                self._db.update_recommendation_status(rec["id"], "resolved")
                resolved_list.append(rec)
            elif status == "ESCALATED":
                note = f"Escalated in review {today_str}"
                self._db.update_recommendation_status(rec["id"], "escalated", note=note)
                escalated_list.append(rec)
            else:
                # CONTINUED or no signal found — leave active
                continued_list.append(rec)

        return {
            "resolved": resolved_list,
            "escalated": escalated_list,
            "continued": continued_list,
        }

    def format_followup_summary(self, followup_result: dict) -> str:
        """
        Format the followup result as a Markdown section for the report.

        Example:
        ### Recommendation Follow-up
        | Recommendation | Category | Priority | Outcome |
        |---|---|---|---|
        | Increase sleep to 7.5h | sleep | HIGH | Resolved |
        | Add Zone 2 cardio 2x/week | cardiovascular | MEDIUM | -> Continued |
        | Reduce training intensity | recovery | HIGH | Escalated |
        """
        resolved = followup_result.get("resolved", [])
        escalated = followup_result.get("escalated", [])
        continued = followup_result.get("continued", [])

        all_entries = (
            [(r, "Resolved") for r in resolved]
            + [(r, "Escalated") for r in escalated]
            + [(r, "Continued") for r in continued]
        )

        if not all_entries:
            return "### Recommendation Follow-up\n\n_No active recommendations were tracked this period._\n"

        outcome_display = {
            "Resolved": "\u2705 Resolved",
            "Escalated": "\u26a0\ufe0f Escalated",
            "Continued": "\u2192 Continued",
        }

        lines = [
            "### Recommendation Follow-up",
            "",
            "| Recommendation | Category | Priority | Outcome |",
            "|---|---|---|---|",
        ]

        for rec, outcome_key in all_entries:
            text = rec.get("text", "")
            # Truncate long texts for the table
            display_text = text[:80] + "..." if len(text) > 80 else text
            category = rec.get("category", "general")
            priority_num = rec.get("priority", PRIORITY_MEDIUM)
            priority_str = PRIORITY_LABEL.get(priority_num, "MEDIUM")
            outcome_str = outcome_display.get(outcome_key, outcome_key)
            lines.append(f"| {display_text} | {category} | {priority_str} | {outcome_str} |")

        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _detect_followup_status(self, response: str, rec_text: str) -> str:
        """
        Search *response* for RESOLVED / CONTINUED / ESCALATED near *rec_text*.

        Returns "RESOLVED", "ESCALATED", or "CONTINUED" (default).

        Strategy:
        1. First attempt an exact substring match of the full rec text.
        2. If not found, fall back to keyword matching.
        3. Once a position is found, search only FORWARD from that position
           (up to FOLLOWUP_WINDOW chars ahead) for the status label.  We avoid
           looking backwards so that a status from a preceding recommendation
           cannot bleed into the current one's detection window.
        """
        # Try exact substring match first
        pos = response.find(rec_text)

        if pos == -1:
            # Fall back to key-word matching: try significant words from rec_text
            pos = self._find_by_keywords(response, rec_text)

        if pos == -1:
            return "CONTINUED"

        # Look forward from the match position only, to avoid picking up status
        # labels that belong to a preceding recommendation.
        forward_start = pos
        forward_end = min(len(response), pos + len(rec_text) + FOLLOWUP_WINDOW)
        forward_context = response[forward_start:forward_end].upper()

        if "RESOLVED" in forward_context:
            return "RESOLVED"
        if "ESCALATED" in forward_context:
            return "ESCALATED"
        # CONTINUED or no signal
        return "CONTINUED"

    @staticmethod
    def _find_by_keywords(response: str, rec_text: str) -> int:
        """
        Attempt to locate *rec_text* in *response* using significant words.

        Splits rec_text into words of 5+ characters and searches for the first
        occurrence of any two consecutive significant words. Returns the index
        of the first match or -1 if not found.
        """
        import re as _re

        words = _re.findall(r'\b\w{5,}\b', rec_text)
        if not words:
            return -1

        # Try pairs of consecutive significant words
        for i in range(len(words) - 1):
            pair = words[i] + r'\W+' + words[i + 1]
            m = _re.search(pair, response, _re.IGNORECASE)
            if m:
                return m.start()

        # Fall back to any single significant word
        for word in words:
            idx = response.lower().find(word.lower())
            if idx != -1:
                return idx

        return -1


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


def get_recommendation_tracker() -> RecommendationTracker:
    """Return singleton RecommendationTracker."""
    global _tracker_singleton
    if _tracker_singleton is None:
        _tracker_singleton = RecommendationTracker(get_db())
    return _tracker_singleton
