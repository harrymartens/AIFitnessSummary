"""Training plan parser for AIFitnessSummary.

Reads a structured markdown training plan and provides plan-aware context
for cadence detection, session adherence, volume targets, and AI prompts.

The plan markdown must follow the format documented in training_plan.md.
"""

import datetime
import os
import re
from pathlib import Path
from typing import Optional


TRAINING_PLAN_PATH = os.getenv(
    "TRAINING_PLAN_PATH",
    str(Path(__file__).parent / "training_plan.md"),
)


def _parse_date(s: str) -> datetime.date:
    """Parse YYYY-MM-DD string to date."""
    return datetime.date.fromisoformat(s.strip())


def _parse_table(lines: list[str]) -> list[dict[str, str]]:
    """Parse a markdown table (header + separator + rows) into list of dicts."""
    if len(lines) < 3:
        return []
    headers = [h.strip() for h in lines[0].strip().strip("|").split("|")]
    rows = []
    for line in lines[2:]:  # skip separator
        line = line.strip()
        if not line or not line.startswith("|"):
            break
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) == len(headers):
            rows.append(dict(zip(headers, cells)))
    return rows


class TrainingPlan:
    """Parsed training plan with block structure and targets."""

    def __init__(self, path: str | None = None):
        self.path = path or TRAINING_PLAN_PATH
        self._raw = ""
        self._meta: dict[str, str] = {}
        self._blocks: list[dict] = []
        self._schedule: dict[str, str] = {}
        self._primary_lifts: list[str] = []
        self._volume_targets: dict[str, list[dict]] = {}
        self._running_targets: dict[str, str | float] = {}
        self._load()

    def _load(self):
        """Parse the training plan markdown file."""
        plan_path = Path(self.path)
        if not plan_path.exists():
            raise FileNotFoundError(
                f"Training plan not found: {plan_path}. "
                "Create a training_plan.md or set TRAINING_PLAN_PATH."
            )
        self._raw = plan_path.read_text(encoding="utf-8")
        self._parse()

    def _parse(self):
        """Parse all sections from the raw markdown."""
        lines = self._raw.splitlines()
        current_section = ""
        current_subsection = ""
        section_lines: list[str] = []
        i = 0

        while i < len(lines):
            line = lines[i]

            # H2 sections
            if line.startswith("## "):
                if current_section:
                    self._process_section(current_section, current_subsection, section_lines)
                current_section = line[3:].strip()
                current_subsection = ""
                section_lines = []
            # H3 subsections
            elif line.startswith("### "):
                if section_lines:
                    self._process_section(current_section, current_subsection, section_lines)
                current_subsection = line[4:].strip()
                section_lines = []
            else:
                section_lines.append(line)
            i += 1

        # Process final section
        if current_section:
            self._process_section(current_section, current_subsection, section_lines)

    def _process_section(self, section: str, subsection: str, lines: list[str]):
        """Route parsed section to the appropriate handler."""
        if section == "Meta":
            self._parse_meta(lines)
        elif section == "Blocks":
            self._parse_block(subsection, lines)
        elif section == "Weekly Schedule":
            self._parse_schedule(lines)
        elif section == "Primary Compound Lifts":
            self._parse_lifts(lines)
        elif section.startswith("Volume Targets"):
            self._parse_volume_targets(subsection, lines)
        elif section.startswith("Running Targets"):
            self._parse_running_targets(lines)

    def _parse_meta(self, lines: list[str]):
        for line in lines:
            m = re.match(r'-\s+\*\*(.+?):\*\*\s+(.+)', line)
            if m:
                self._meta[m.group(1).strip().lower()] = m.group(2).strip()

    def _parse_block(self, name: str, lines: list[str]):
        if not name:
            return
        block: dict = {"name": name}
        for line in lines:
            m = re.match(r'-\s+\*\*(.+?):\*\*\s+(.+)', line)
            if m:
                key = m.group(1).strip().lower()
                val = m.group(2).strip()
                if key == "type":
                    block["type"] = val
                elif key == "start":
                    block["start"] = _parse_date(val)
                elif key == "end":
                    block["end"] = _parse_date(val)
                elif key == "deload week":
                    parts = val.split(" to ")
                    if len(parts) == 2:
                        block["deload_start"] = _parse_date(parts[0])
                        block["deload_end"] = _parse_date(parts[1])
        if "start" in block:
            self._blocks.append(block)

    def _parse_schedule(self, lines: list[str]):
        for line in lines:
            m = re.match(r'-\s+\*\*(.+?):\*\*\s+(.+)', line)
            if m:
                self._schedule[m.group(1).strip()] = m.group(2).strip()

    def _parse_lifts(self, lines: list[str]):
        for line in lines:
            m = re.match(r'-\s+(.+)', line)
            if m:
                self._primary_lifts.append(m.group(1).strip())

    def _parse_volume_targets(self, subsection: str, lines: list[str]):
        # Find the table in the lines
        table_lines = [l for l in lines if l.strip().startswith("|") or l.strip().startswith("---")]
        # Filter to actual table lines
        table_lines = [l for l in lines if "|" in l]
        if not table_lines:
            return
        rows = _parse_table(table_lines)
        key = subsection.lower().replace(" ", "_") if subsection else "default"
        self._volume_targets[key] = rows

    def _parse_running_targets(self, lines: list[str]):
        for line in lines:
            m = re.match(r'-\s+\*\*(.+?):\*\*\s+(.+)', line)
            if m:
                key = m.group(1).strip().lower().replace(" ", "_")
                val = m.group(2).strip()
                # Try to extract numeric value
                num_match = re.match(r'([\d.]+)', val)
                if num_match and key in ("weekly_volume", "threshold_hr"):
                    self._running_targets[key] = float(num_match.group(1))
                else:
                    self._running_targets[key] = val

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def programme_name(self) -> str:
        return self._meta.get("programme", "Unknown Programme")

    @property
    def goal_statement(self) -> str:
        return self._meta.get("goal", "")

    @property
    def start_date(self) -> Optional[datetime.date]:
        val = self._meta.get("start date")
        return _parse_date(val) if val else None

    @property
    def end_date(self) -> Optional[datetime.date]:
        val = self._meta.get("end date")
        return _parse_date(val) if val else None

    @property
    def bodyweight_target_rate(self) -> Optional[str]:
        return self._meta.get("bodyweight target rate")

    @property
    def protein_target(self) -> Optional[str]:
        return self._meta.get("protein target")

    @property
    def blocks(self) -> list[dict]:
        return self._blocks

    @property
    def primary_lifts(self) -> list[str]:
        return self._primary_lifts

    @property
    def weekly_schedule(self) -> dict[str, str]:
        return self._schedule

    @property
    def running_targets(self) -> dict:
        return self._running_targets

    def get_current_block(self, date: datetime.date | None = None) -> Optional[dict]:
        """Return the block containing the given date, or None if outside plan."""
        date = date or datetime.date.today()
        for block in self._blocks:
            if block["start"] <= date <= block["end"]:
                return block
        return None

    def get_block_week_number(self, date: datetime.date | None = None) -> Optional[int]:
        """Return the 1-based week number within the current block."""
        date = date or datetime.date.today()
        block = self.get_current_block(date)
        if not block:
            return None
        days_in = (date - block["start"]).days
        return (days_in // 7) + 1

    def get_programme_week_number(self, date: datetime.date | None = None) -> Optional[int]:
        """Return the 1-based week number within the overall programme."""
        date = date or datetime.date.today()
        start = self.start_date
        if not start or date < start:
            return None
        days_in = (date - start).days
        return (days_in // 7) + 1

    def is_deload_week(self, date: datetime.date | None = None) -> bool:
        """Return True if the given date falls in a deload week."""
        date = date or datetime.date.today()
        block = self.get_current_block(date)
        if not block:
            return False
        deload_start = block.get("deload_start")
        deload_end = block.get("deload_end")
        if deload_start and deload_end:
            return deload_start <= date <= deload_end
        return False

    def is_final_week(self, date: datetime.date | None = None) -> bool:
        """Return True if the given date falls in the final week of the programme."""
        date = date or datetime.date.today()
        end = self.end_date
        if not end:
            return False
        final_week_start = end - datetime.timedelta(days=6)
        return final_week_start <= date <= end

    def get_cadence_type(self, date: datetime.date | None = None) -> str:
        """Determine the check-in type for the given date.

        Returns one of: 'end_of_programme', 'block_checkin', 'weekly'
        Block check-in replaces (not supplements) the weekly digest in deload weeks.
        """
        date = date or datetime.date.today()
        if self.is_final_week(date):
            return "end_of_programme"
        if self.is_deload_week(date):
            return "block_checkin"
        return "weekly"

    def get_volume_targets(self, block_type: str | None = None) -> dict[str, dict]:
        """Return volume targets for the given block type.

        Returns dict mapping muscle group name → {min, target, max}.
        """
        if block_type is None:
            block = self.get_current_block()
            block_type = block["type"] if block else "hypertrophy"

        # Map block type to volume target key
        key_map = {
            "hypertrophy": "hypertrophy_blocks",
            "strength": "strength_blocks",
        }
        key = key_map.get(block_type, "hypertrophy_blocks")
        rows = self._volume_targets.get(key, [])

        result = {}
        for row in rows:
            name = row.get("Muscle Group", "")
            if name:
                try:
                    result[name] = {
                        "min": int(row.get("Min Sets", 0)),
                        "target": int(row.get("Target Sets", 0)),
                        "max": int(row.get("Max Sets", 0)),
                    }
                except (ValueError, TypeError):
                    pass
        return result

    def get_planned_sessions_per_week(self) -> int:
        """Return the number of planned training sessions (strength) per week."""
        count = 0
        for day, session in self._schedule.items():
            session_lower = session.lower()
            if any(kw in session_lower for kw in ("strength", "upper", "lower", "body", "hypertrophy", "push", "pull")):
                count += 1
        return count

    def get_planned_runs_per_week(self) -> int:
        """Return the number of planned runs per week."""
        count = 0
        for day, session in self._schedule.items():
            if "run" in session.lower():
                count += 1
        return count

    def get_planned_weekly_km(self) -> Optional[float]:
        """Return the planned weekly running volume in km."""
        val = self._running_targets.get("weekly_volume")
        if isinstance(val, (int, float)):
            return float(val)
        return None

    def get_threshold_hr(self) -> Optional[int]:
        """Return the aerobic threshold HR for pace-at-HR calculations."""
        val = self._running_targets.get("threshold_hr")
        if isinstance(val, (int, float)):
            return int(val)
        return None

    def get_intensity_distribution_target(self) -> Optional[str]:
        """Return the target intensity distribution (e.g. '80% easy / 20% hard')."""
        return self._running_targets.get("intensity_distribution")

    def get_plan_context_for_prompt(self, date: datetime.date | None = None) -> str:
        """Format the training plan as a structured text block for the AI system prompt.

        Includes: programme name, goal, current block, week number, volume targets,
        running targets, and primary lifts.
        """
        date = date or datetime.date.today()
        block = self.get_current_block(date)
        block_week = self.get_block_week_number(date)
        prog_week = self.get_programme_week_number(date)
        cadence = self.get_cadence_type(date)

        lines = ["[TRAINING PLAN]"]
        lines.append(f"Programme: {self.programme_name}")
        lines.append(f"Goal: {self.goal_statement}")

        if block:
            lines.append(f"Current Block: {block['name']} ({block['type']})")
            lines.append(f"Block Week: {block_week} of {((block['end'] - block['start']).days // 7) + 1}")
        if prog_week:
            lines.append(f"Programme Week: {prog_week}")

        lines.append(f"Check-In Type: {cadence}")
        lines.append(f"Is Deload: {'Yes' if self.is_deload_week(date) else 'No'}")

        # Volume targets
        if block:
            targets = self.get_volume_targets(block["type"])
            if targets:
                lines.append("")
                lines.append("Volume Targets (sets/week):")
                for group, t in targets.items():
                    lines.append(f"  {group}: {t['min']}-{t['max']} (target {t['target']})")

        # Running targets
        planned_km = self.get_planned_weekly_km()
        threshold_hr = self.get_threshold_hr()
        if planned_km:
            lines.append("")
            lines.append(f"Running: {planned_km} km/week planned")
        if threshold_hr:
            lines.append(f"Threshold HR: {threshold_hr} bpm")
        intensity = self.get_intensity_distribution_target()
        if intensity:
            lines.append(f"Intensity Target: {intensity}")

        # Primary lifts
        if self._primary_lifts:
            lines.append("")
            lines.append(f"Primary Compound Lifts: {', '.join(self._primary_lifts)}")

        # Planned sessions
        lines.append(f"Planned Strength Sessions/Week: {self.get_planned_sessions_per_week()}")
        lines.append(f"Planned Runs/Week: {self.get_planned_runs_per_week()}")

        # Nutrition
        bw_rate = self.bodyweight_target_rate
        protein = self.protein_target
        if bw_rate:
            lines.append(f"Bodyweight Target Rate: {bw_rate}")
        if protein:
            lines.append(f"Protein Target: {protein}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level loader
# ---------------------------------------------------------------------------

_plan_singleton: Optional[TrainingPlan] = None


def get_plan() -> Optional[TrainingPlan]:
    """Return the TrainingPlan singleton, or None if no plan file exists."""
    global _plan_singleton
    if _plan_singleton is None:
        try:
            _plan_singleton = TrainingPlan()
        except FileNotFoundError:
            return None
    return _plan_singleton


def load_plan(path: str | None = None) -> TrainingPlan:
    """Load a training plan from the given path. Raises FileNotFoundError if missing."""
    return TrainingPlan(path=path)
