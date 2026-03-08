# Architecture Reference

Technical reference for the AIFitnessSummary system. Intended for contributors,
future maintainers, and anyone debugging a specific part of the pipeline.

## Module Overview

| Module | Role |
|--------|------|
| `main.py` | Entry point, CLI argument parsing, review pipeline orchestration |
| `config.py` | Constants (model name, date format, report directory, valid periods) and date-range helper |
| `db_client.py` | SQLite persistence layer — all reads and writes to `fitness_memory.db` |
| `garmin_client.py` | Garmin Connect API client — authentication with token caching, all metric fetchers |
| `hevy_client.py` | Hevy REST API client — workout pagination, exercise template lookup, summary computation |
| `claude_analyzer.py` | Anthropic Claude integration — prompt assembly, narrative generation, recommendation parsing |
| `report_generator.py` | Markdown report assembly — data tables + Claude narrative into a formatted file |
| `email_client.py` | Gmail SMTP delivery — Markdown-to-HTML conversion, styled HTML email |
| `goal_manager.py` | Goal wizard (interactive CLI), AI-assisted goal parsing, goal formatting for prompts |
| `trend_analyzer.py` | Historical snapshot persistence and trend context string generation |
| `recommendation_tracker.py` | Recommendation lifecycle — save, follow up, status updates |
| `knowledge_client.py` | Knowledge base topic selection + PubMed/examine.com research with 30-day cache |
| `scheduler.py` | Daemon scheduling loop and crontab management with catch-up logic |

### Key design decisions

- **Singleton pattern** for shared resources: `get_db()` returns a
  module-level `DatabaseClient` singleton; `get_email_client()` returns a
  module-level `EmailClient` singleton (or `None` if email is unconfigured).
  This avoids multiple DB connections within a single review run.
- **Graceful degradation**: every data-fetching step in `main.run_review()` is
  wrapped in `try/except`. A failure to fetch Garmin data, Hevy data, or
  research context prints a warning to stderr and continues — the review runs
  with whatever data is available.
- **Fail-open email**: if `EMAIL_SENDER`, `EMAIL_RECIPIENT`, or
  `GMAIL_APP_PASSWORD` are absent, `get_email_client()` returns `None` and
  email is silently skipped. Reports are always written to disk regardless.
- **`.env` loaded before module imports**: `main.py` calls `load_dotenv()`
  before any application module is imported, so modules that read environment
  variables at import time (e.g. config constants) see the correct values.

---

## Database Schema

All data is stored in a single SQLite file (`fitness_memory.db` by default,
overridable via `DB_PATH` environment variable).

### `goals`

Stores user-defined fitness goals. Only one goal should be active at a time
(`is_active = 1`); deactivation sets `is_active = 0` without deleting the row.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment primary key |
| `created_at` | TEXT | ISO-8601 UTC timestamp of goal creation |
| `updated_at` | TEXT | ISO-8601 UTC timestamp of last update |
| `primary_objective` | TEXT NOT NULL | Human-readable goal description (e.g. "Weight Loss") |
| `target_weight_kg` | REAL | Target body weight in kilograms (nullable) |
| `target_steps_per_day` | INTEGER | Daily step count target (nullable) |
| `target_sleep_hours` | REAL | Target sleep duration per night (nullable) |
| `target_workouts_per_week` | INTEGER | Target training sessions per week (nullable) |
| `target_resting_hr` | INTEGER | Target resting heart rate in bpm (nullable) |
| `target_vo2max` | REAL | Target VO2max in ml/kg/min (nullable) |
| `timeline_weeks` | INTEGER | Goal duration in weeks (nullable) |
| `notes` | TEXT | Free-text notes and context (nullable) |
| `is_active` | INTEGER | 1 = active, 0 = deactivated. Default 1. |
| `is_provisional` | INTEGER | 1 = AI-inferred, awaiting user confirmation. Default 0. |

### `reviews`

One row per generated review. Stores the key aggregate metrics for trend
analysis and report lookup.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment primary key |
| `period` | TEXT | `"weekly"` or `"monthly"` |
| `start_date` | TEXT | ISO-8601 date (`YYYY-MM-DD`) |
| `end_date` | TEXT | ISO-8601 date (`YYYY-MM-DD`) |
| `generated_at` | TEXT | ISO-8601 UTC timestamp of review generation |
| `report_path` | TEXT | Absolute path to the generated Markdown file (nullable) |
| `avg_steps` | REAL | Average daily step count for the period |
| `avg_sleep_hours` | REAL | Average total sleep per night (hours) |
| `avg_resting_hr` | REAL | Average resting heart rate (bpm) |
| `avg_hrv` | REAL | Average HRV weekly average (ms) |
| `avg_stress` | REAL | Average Garmin stress score (0–100) |
| `avg_body_battery` | REAL | Average body battery charged value |
| `avg_spo2` | REAL | Average blood oxygen saturation (%) |
| `avg_vo2max` | REAL | VO2max estimate at end of period (ml/kg/min) |
| `avg_weight_kg` | REAL | Average body weight (kg) |
| `avg_body_fat_pct` | REAL | Average body fat percentage |
| `workouts_count` | INTEGER | Number of Hevy workouts in the period |
| `total_volume_kg` | REAL | Total training volume (sets × reps × weight, kg) |
| `total_run_distance_km` | REAL | Total running distance (km) |

### `metrics_history`

Per-day metric values linked to a review. Currently populated with daily step
counts; the schema is generic to accommodate additional metrics.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment primary key |
| `review_id` | INTEGER FK | Foreign key to `reviews.id` |
| `date` | TEXT | ISO-8601 date (`YYYY-MM-DD`) |
| `metric_name` | TEXT | Metric identifier, e.g. `"steps"` |
| `metric_value` | REAL | Numeric value (nullable) |

### `recommendations`

One row per actionable recommendation extracted from a Claude response.
Status transitions: `active` → `resolved` / `escalated` / `deprioritized`.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment primary key |
| `review_id` | INTEGER FK | Foreign key to `reviews.id` |
| `category` | TEXT | One of: `sleep`, `training`, `recovery`, `cardiovascular`, `nutrition`, `general` |
| `priority` | INTEGER | 1 = HIGH, 2 = MEDIUM, 3 = LOW |
| `text` | TEXT | Full recommendation text |
| `status` | TEXT | `active`, `resolved`, `escalated`, or `deprioritized`. Default `active`. |
| `created_at` | TEXT | ISO-8601 UTC timestamp |
| `resolved_at` | TEXT | ISO-8601 UTC timestamp when status changed to a terminal state (nullable) |
| `resolution_note` | TEXT | Short note on how the recommendation was resolved (nullable) |

### `knowledge_cache`

Caches results from PubMed and examine.com queries to avoid redundant network
requests. TTL is 30 days.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment primary key |
| `cache_key` | TEXT UNIQUE | SHA-256 hash of source + query string |
| `source` | TEXT | Source identifier, e.g. `"pubmed"` or `"examine"` |
| `query` | TEXT | The original search query |
| `result_text` | TEXT | The fetched and processed result text |
| `fetched_at` | TEXT | ISO-8601 UTC timestamp when fetched |
| `expires_at` | TEXT | ISO-8601 UTC timestamp when the cache entry expires |

---

## Review Pipeline Flow

The following sequence executes when `main.run_review(period)` is called
(whether manually or by the scheduler):

```
1.  get_db()
    └─ Open / reuse SQLite connection; create schema if needed

2.  config.get_date_range(period)
    └─ Compute start_date = yesterday − (6 or 29 days)
       end_date = yesterday

3.  GoalManager.get_active_goal()
    └─ SELECT * FROM goals WHERE is_active=1 ORDER BY id DESC LIMIT 1
       Returns None if no goal — handled gracefully in steps 9 and 12

4.  TrendAnalyzer.get_trend_context(n=6)
    └─ SELECT last 6 reviews from DB
       Format as a [HISTORICAL CONTEXT] text block for Claude prompt

5.  RecommendationTracker.get_active_for_prompt()
    └─ SELECT * FROM recommendations WHERE status='active'
       Format as a [PREVIOUS RECOMMENDATIONS] text block

6.  GarminClient.collect_all(start_date, end_date)
    └─ Authenticate (load cached tokens or interactive MFA on first run)
       Fetch: steps/activity, heart rates, sleep, stress, body battery,
              HRV, SpO2, respiration, training readiness, training load,
              VO2max, body composition, running activities

7.  HevyClient.fetch_workouts(start_date, end_date) + summarise_workouts()
    └─ Paginate /v1/workouts (10 per page), filter to period
       Fetch exercise templates for muscle-group lookup
       Compute: workout count, volume by muscle group, exercise breakdown, PRs

8.  get_knowledge_context(garmin_data)
    └─ select_relevant_topics() — heuristic rules pick up to 2 topics
       Load matching knowledge_base/*.md file(s)
       Return as [KNOWLEDGE BASE — TOPIC] block

    get_research_context(garmin_data, goal)
    └─ Build PubMed query from metrics and goal
       Check knowledge_cache (30-day TTL)
       If cache miss: query PubMed API + scrape examine.com
       Cache result; return as [RESEARCH CONTEXT] block

9.  ClaudeAnalyzer.generate_review(...)
    └─ Assemble prompt:
         [ACTIVE GOAL] (if goal exists)
         [HISTORICAL CONTEXT] (last 6 reviews)
         [PREVIOUS RECOMMENDATIONS] (active items)
         [KNOWLEDGE BASE — TOPIC] (1–2 topics)
         [RESEARCH CONTEXT] (PubMed / examine.com)
         REVIEW PERIOD + garmin_data + hevy_summary
       Call Anthropic API (claude-sonnet-4-6, max_tokens=4096)
       Return full narrative text including ---RECOMMENDATIONS--- block

10. TrendAnalyzer.save_review(period, start_date, end_date, garmin_data, hevy_data)
    └─ Extract aggregate metrics; INSERT INTO reviews
       INSERT daily steps into metrics_history
       Return review_id

    RecommendationTracker.save_from_response(review_id, narrative)
    └─ parse_recommendations() — extract ---RECOMMENDATIONS--- block
       Filter to HIGH/MEDIUM priority (≥2 items required)
       INSERT INTO recommendations

    RecommendationTracker.process_followup(narrative)
    └─ For each active recommendation, search narrative for resolution keywords
       UPDATE recommendations SET status=... WHERE matched
       Return follow-up result dict

    RecommendationTracker.format_followup_summary(result)
    └─ Format resolved / still-active items as a Markdown section string

11. ClaudeAnalyzer.strip_recommendations_block(narrative)
    └─ Remove ---RECOMMENDATIONS--- ... ---END RECOMMENDATIONS--- from narrative
       Return clean narrative for inclusion in the human-readable report

12. ReportGenerator.generate(...)
    └─ Build Markdown sections:
         Header (period, dates, generation time, sources)
         Active Goal (if goal exists)
         Trend Summary (from trend_context_str)
         Recommendation Follow-up (from followup_summary_str)
         Garmin data tables (one table per metric category)
         Hevy data tables (workouts, volume, exercises, PRs)
         Claude narrative sections (split by ## heading)
    Write to reports/{period}_review_{end_date}.md
    Return Path object

13. UPDATE reviews SET report_path=? WHERE id=?
    └─ Store the report file path for future reference

14. EmailClient.send_report(period, end_date, report_content)
    └─ Convert Markdown to styled HTML
       Send via Gmail SMTP SSL (port 465)
       Skip silently if EmailClient is None (unconfigured)
```

---

## Claude Prompt Structure

Each call to `ClaudeAnalyzer.generate_review()` assembles a user prompt with
the following sections in order. Sections are only included if the relevant
data is available.

```
[ACTIVE GOAL]
Primary Objective: <goal.primary_objective>
Target Weight: <goal.target_weight_kg> kg
Target Steps/Day: <goal.target_steps_per_day>
Target Sleep: <goal.target_sleep_hours> hrs/night
Target Workouts/Week: <goal.target_workouts_per_week>
Target Resting HR: <goal.target_resting_hr> bpm
Target VO2 Max: <goal.target_vo2max> ml/kg/min
Timeline: <goal.timeline_weeks> weeks
Notes: <goal.notes>
Status: Active (confirmed) | Provisional (unconfirmed)

[HISTORICAL CONTEXT]
<Formatted table of last N reviews with metric trends and direction arrows>

[PREVIOUS RECOMMENDATIONS]
<Numbered list of active recommendations with category and priority>

[KNOWLEDGE BASE — <TOPIC>]
<Full contents of the relevant knowledge_base/*.md file>

[RESEARCH CONTEXT]
<Summarised PubMed abstracts and/or examine.com content>

REVIEW PERIOD: <period> | <start_date> → <end_date>

GARMIN DATA:
<JSON-like dump of all garmin_data sub-dicts>

HEVY DATA:
<JSON-like dump of hevy_summary>
```

The system prompt (`claude_analyzer.SYSTEM_PROMPT`) instructs Claude to:

- Write in a warm, motivating, but honest tone, referencing actual numbers.
- Use these exact section headings in order:
  `## Executive Summary`, `## Activity & Cardiovascular Highlights`,
  `## Sleep Quality`, `## Recovery & Stress`, `## Strength Training Analysis`,
  `## Training Load Assessment`, `## Recommendations for Next Period`
- Stay under 1200 words.
- Frame all observations relative to the active goal.
- Draw on `[KNOWLEDGE BASE]` content to support recommendations.
- Only cite sources that appear in the provided `[RESEARCH CONTEXT]`.
- Output a structured `---RECOMMENDATIONS---` block after the narrative.

### Recommendations block format

Claude is instructed to output exactly this structure after the narrative:

```
---RECOMMENDATIONS---
[HIGH] category: text of recommendation
[MEDIUM] category: text of recommendation
[LOW] category: text of recommendation
---END RECOMMENDATIONS---
```

This block is parsed by `ClaudeAnalyzer.parse_recommendations()` using regex,
saved to the `recommendations` DB table, and then stripped from the narrative
before the report is assembled.

---

## Knowledge Base Topics

Five curated Markdown files live in `knowledge_base/`. Each covers a topic
relevant to recreational fitness, written at a level suitable for direct
injection into a Claude prompt.

| Topic key | File | Contents |
|-----------|------|----------|
| `cardiovascular` | `cardiovascular.md` | VO2max norms by age/sex, heart rate zones, aerobic training adaptations, cardiovascular risk markers |
| `hrv` | `hrv_interpretation.md` | Autonomic nervous system physiology, HRV measurement methodology, population ranges, training readiness interpretation, lifestyle factors |
| `recovery` | `recovery.md` | Recovery timescales (acute/short-term/long-term), physiological mechanisms, body battery interpretation, practical recovery strategies |
| `sleep` | `sleep_science.md` | Sleep architecture (NREM stages, REM), stage functions, recommended durations, athletic performance impacts, sleep debt |
| `strength_training` | `strength_training.md` | Progressive overload, volume landmarks (MEV/MAV/MRV framework), periodisation approaches, hypertrophy mechanisms, frequency recommendations |

### Topic selection heuristics

`knowledge_client.select_relevant_topics()` selects at most 2 topics per review
based on the following rules (evaluated in priority order):

1. HRV weekly average < 50 ms or declining → add `hrv` and `recovery`
2. Average sleep < 6.5 hours or deep sleep < 15% of total → add `sleep`
3. Hevy workout count ≥ 3 in the period → add `strength_training`
4. VO2max data present or running distance > 0 → add `cardiovascular`
5. Average stress > 60 or average body battery charged < 40 → add `recovery`
6. Default fallback (no rules triggered): `strength_training` and `sleep`

---

## Scheduling

### Daemon mode

`python scheduler.py` (or `python scheduler.py daemon`) runs an infinite loop
using the `schedule` library. The main loop sleeps for 30 seconds between
checks (`schedule.run_pending()`).

Registered jobs:
- `schedule.every().monday.at("07:00")` → `run_review("weekly")`
- `schedule.every().day.at("07:00")` → `_monthly_check()` (only runs
  `run_review("monthly")` if today is the 1st of the month)

On startup, `check_and_run_catchup()` is called before the loop begins.

### Cron mode

`python scheduler.py install-cron` appends the following two lines to the
current user's crontab, tagged with `# AIFitnessSummary`:

```
0 7 * * 1  cd /path/to/project && /path/to/python main.py --period weekly  >> /path/to/project/reports/cron.log 2>&1
0 7 1 * *  cd /path/to/project && /path/to/python main.py --period monthly >> /path/to/project/reports/cron.log 2>&1
```

Paths are resolved at install time using `Path(__file__).parent.resolve()` and
`sys.executable`, so the entries are always absolute and correct regardless of
the working directory at the time of installation.

`python scheduler.py remove-cron` removes all lines in the crontab between the
`# AIFitnessSummary` marker and the next blank line.

`python scheduler.py show-cron` prints the entries that would be installed
without modifying anything (equivalent to `--dry-run` for inspection).

### Catch-up logic

On daemon startup, `check_and_run_catchup()` checks whether any scheduled
review was missed:

- **Weekly**: if `now.weekday()` is 1 (Tuesday) or 2 (Wednesday), the most
  recent Monday at 07:00 is computed. If that timestamp is in the past and
  less than 48 hours ago, a weekly review runs immediately.
- **Monthly**: if `now.day` is 2 or 3, the 1st of the current month at 07:00
  is computed. If that timestamp is in the past and less than 48 hours ago, a
  monthly review runs immediately.

The 48-hour window means catch-up only fires when the machine has been off for
at most 2 days. Beyond that window, the missed review is not run (it would
produce a report for a period that might already have a following review).

Cron mode does not implement catch-up — cron jobs are expected to be managed
by the OS scheduler and will simply not fire if the machine is off.
