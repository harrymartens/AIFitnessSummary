"""Claude AI integration for AIFitnessSummary.

Generates structured natural language summaries — not data printouts.
Interprets numbers in context of the training plan and goals,
identifies patterns across metrics, flags risks, and issues
concrete recommendations.

Prompt architecture per proposal Section 6:
- System prompt: training plan, block/week, goal, volume targets
- User prompt: aggregated summary statistics only, never raw logs
- Tone: direct, specific, brief — not motivational
- Token budgets: 700-900 weekly, 1200-1500 block check-in
"""

import re

import anthropic

from config import get_max_tokens, MODEL

# ---------------------------------------------------------------------------
# System prompts per cadence (Section 6.1)
# ---------------------------------------------------------------------------

WEEKLY_SYSTEM_PROMPT = """\
You are an expert concurrent-training coach analysing a weekly fitness digest. \
You will receive aggregated summary statistics (never raw data) covering the past 7 days, \
plus the athlete's training plan context.

Be direct, specific, and brief. Do not be motivational. Reference actual numbers. \
Every observation must connect to training adaptation or recovery.

Structure your response with these exact Markdown headings:
## Overall Assessment
One sentence: is this week on track or not, and why.

## Sleep
Quality and consistency signal. Flag bedtime SD, efficiency, or duration issues.

## Strength
Volume adequacy per muscle group vs targets. Progressive overload status. Session adherence.

## Running
Volume compliance vs plan. Intensity distribution (easy/hard %). Quality session fidelity if data present.

## Recovery
RHR trend and HRV status. Flag if either indicates accumulated fatigue.

## Nutrition
Protein adequacy, calorie adherence, bodyweight trend direction.

## Action Item
One single concrete recommendation for the coming week. Be specific.

ESCALATION FLAGS:
If escalation flags are provided in the data, incorporate them into the relevant section \
with advisory language. These are pre-computed threshold breaches that require explicit mention.

Keep total response under 800 words. Do not repeat raw numbers as tables. \
Do not output a recommendations block — the action item section IS the recommendation.\
"""

BLOCK_CHECKIN_SYSTEM_PROMPT = """\
You are an expert concurrent-training coach conducting a block check-in during a deload week. \
You will receive aggregated metrics for this week plus block-level context.

Be direct, specific, and brief. Do not be motivational. Reference actual numbers.

Structure your response with these exact Markdown headings:
## Block Assessment
Was this block effective for its stated goal (hypertrophy or strength)?

## Strength Adaptation
Load and hypertrophy adaptation review. Estimated 1RM changes on primary lifts. \
Volume progression per muscle group across the block. Stalled exercises.

## Running Adaptation
Is pace-at-threshold-HR improving? Quality session pace trend. \
Weekly km progression. VO2max direction (supporting evidence only).

## Body Composition
Is the gain/loss rate appropriate for the block goal? Weight trend vs target rate.

## Concurrent Interference
Was interference detected? Lower body strength in high-mileage weeks. \
Intensity distribution. RHR + volume correlation.

## Recovery Health
RHR trend across the block. Training Status label. Was load appropriate?

## Programme Recommendation
Specific changes for the next block. Options: continue / adjust load / \
modify exercise selection / adjust run-lift sequencing / extend deload.

Keep total response under 1400 words.\
"""

END_OF_PROGRAMME_SYSTEM_PROMPT = """\
You are an expert concurrent-training coach conducting an end-of-programme review. \
You will receive aggregated metrics for the final week plus full-programme context.

Be direct, specific, and brief. Do not be motivational. Reference actual numbers.

Structure your response with these exact Markdown headings:
## Goal Achievement
Were the programme targets met? Strength numbers, running performance, body composition.

## Biggest Adaptation Wins
What improved most and why. Cite specific metric changes.

## Gaps
What did not improve or regressed. Identify root causes.

## Structural Carry-Forward
What programme elements worked well and should be maintained.

## Next Block Recommendation
Recommended structure: which qualities to prioritise, which are well-developed, \
what to load-manage. Suggest specific block type and focus.

Keep total response under 1400 words.\
"""


def _get_system_prompt(cadence: str) -> str:
    """Return the appropriate system prompt for the cadence type."""
    if cadence == "block_checkin":
        return BLOCK_CHECKIN_SYSTEM_PROMPT
    if cadence == "end_of_programme":
        return END_OF_PROGRAMME_SYSTEM_PROMPT
    return WEEKLY_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Data formatting for prompts
# ---------------------------------------------------------------------------

def _format_plan_context(plan_context: str) -> str:
    """Format plan context block for the prompt."""
    if not plan_context:
        return "[TRAINING PLAN]\nNo training plan loaded."
    return plan_context


def _format_escalation_flags(flags: list[dict]) -> str:
    """Format escalation flags for the prompt."""
    if not flags:
        return ""
    lines = ["[ESCALATION FLAGS — MUST BE ADDRESSED IN RELEVANT SECTIONS]"]
    for flag in flags:
        lines.append(f"- {flag['condition']} → {flag['advisory']}")
    return "\n".join(lines)


def _format_weekly_data(summary: dict) -> str:
    """Format aggregated weekly summary statistics for the user prompt."""
    lines = []

    # Sleep
    lines.append("=== SLEEP ===")
    lines.append(f"Average duration: {summary.get('sleep_avg_duration_h')} hours")
    lines.append(f"Bedtime consistency (SD): {summary.get('sleep_bedtime_consistency_sd_min')} minutes")
    lines.append(f"Sleep efficiency: {summary.get('sleep_efficiency_pct')}%")
    lines.append(f"Sleep respiratory rate: {summary.get('sleep_respiration_brpm')} brpm")
    lines.append(f"Overnight RHR: {summary.get('overnight_rhr_avg_bpm')} bpm")
    lines.append(f"Nights tracked: {summary.get('sleep_nights_tracked')}")

    # Strength
    lines.append("")
    lines.append("=== STRENGTH ===")
    completed = summary.get('strength_sessions_completed', 0)
    planned = summary.get('strength_sessions_planned')
    adherence = summary.get('strength_session_adherence_pct')
    lines.append(f"Sessions completed: {completed}" + (f" / {planned} planned ({adherence}%)" if planned else ""))

    sets_per_group = summary.get("sets_per_muscle_group", {})
    volume_targets = summary.get("volume_targets", {})
    if sets_per_group:
        lines.append("Sets per muscle group (vs target range):")
        for group, sets in sets_per_group.items():
            target = volume_targets.get(group, {})
            if target:
                lines.append(f"  {group}: {sets} sets (target {target.get('min')}-{target.get('max')})")
            else:
                lines.append(f"  {group}: {sets} sets")

    top_sets = summary.get("primary_lift_top_sets", {})
    if top_sets:
        lines.append("Primary compound lift top sets:")
        for lift, data in top_sets.items():
            lines.append(f"  {lift}: {data['weight_kg']}kg x {data['reps']} (est. 1RM: {data['estimated_1rm']}kg)")

    # Running
    lines.append("")
    lines.append("=== RUNNING ===")
    total_km = summary.get('running_total_km', 0)
    planned_km = summary.get('running_planned_km')
    compliance = summary.get('running_volume_compliance_pct')
    lines.append(f"Total volume: {total_km} km" + (f" / {planned_km} km planned ({compliance}%)" if planned_km else ""))
    lines.append(f"Intensity: {summary.get('running_easy_pct')}% easy / {summary.get('running_hard_pct')}% hard")
    lines.append(f"Easy km: {summary.get('running_easy_km')} | Hard km: {summary.get('running_hard_km')}")
    lines.append(f"Runs completed: {summary.get('run_count', 0)}" + (f" / {summary.get('runs_planned')} planned" if summary.get('runs_planned') else ""))

    # Recovery
    lines.append("")
    lines.append("=== RECOVERY ===")
    lines.append(f"7-day avg resting HR: {summary.get('resting_hr_avg_bpm')} bpm")
    lines.append(f"HRV 7-day status: {summary.get('hrv_status_label')}")

    # Nutrition
    lines.append("")
    lines.append("=== NUTRITION ===")
    lines.append(f"Avg daily protein: {summary.get('nutrition_avg_protein_g')} g")
    lines.append(f"Avg daily calories: {summary.get('nutrition_avg_calories')}")
    lines.append(f"7-day avg bodyweight: {summary.get('bodyweight_avg_kg')} kg")

    return "\n".join(lines)


def _format_block_data(summary: dict) -> str:
    """Format aggregated block check-in data for the user prompt."""
    weekly = _format_weekly_data(summary)

    lines = [weekly]
    lines.append("")
    lines.append("=== BLOCK-LEVEL METRICS ===")
    lines.append(f"Training Status: {summary.get('training_status_label')}")
    lines.append(f"VO2max estimate: {summary.get('vo2max_estimate')}")

    return "\n".join(lines)


def format_data_for_prompt(
    cadence: str,
    start_date: str,
    end_date: str,
    summary: dict,
    plan_context: str = "",
    escalation_flags: list[dict] | None = None,
) -> str:
    """Assemble the complete user prompt from aggregated data.

    Only passes summary statistics — never raw daily data, GPS tracks,
    HR samples, food logs, or individual sets.
    """
    lines = []

    # Plan context (always first)
    lines.append(_format_plan_context(plan_context))
    lines.append("")

    # Escalation flags
    if escalation_flags:
        lines.append(_format_escalation_flags(escalation_flags))
        lines.append("")

    # Period header
    lines.append(f"REVIEW PERIOD: {cadence.upper().replace('_', ' ')} ({start_date} to {end_date})")
    lines.append("")

    # Aggregated data
    if cadence in ("block_checkin", "end_of_programme"):
        lines.append(_format_block_data(summary))
    else:
        lines.append(_format_weekly_data(summary))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Claude API client
# ---------------------------------------------------------------------------

class ClaudeAnalyzer:
    """Uses the Anthropic API to generate fitness digest summaries."""

    def __init__(self):
        self._client = anthropic.Anthropic()

    def generate_review(
        self,
        cadence: str,
        start_date: str,
        end_date: str,
        summary: dict,
        plan_context: str = "",
        escalation_flags: list[dict] | None = None,
    ) -> str:
        """Generate the AI summary for the given cadence.

        Args:
            cadence: 'weekly', 'block_checkin', or 'end_of_programme'
            start_date: ISO date string
            end_date: ISO date string
            summary: aggregated metrics from aggregator.py
            plan_context: formatted plan context from plan_client
            escalation_flags: list of flag dicts from aggregator.detect_escalation_flags
        """
        system_prompt = _get_system_prompt(cadence)
        user_content = format_data_for_prompt(
            cadence, start_date, end_date, summary,
            plan_context=plan_context,
            escalation_flags=escalation_flags,
        )

        max_tokens = get_max_tokens(cadence)

        print(f"Generating Claude {cadence} analysis...")
        response = self._client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        return response.content[0].text
