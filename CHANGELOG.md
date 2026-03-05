# Changelog

All notable changes to AIFitnessSummary are documented here.

## [Unreleased] — Enhancement Branch (`claude/plan-app-enhancement-5Mkht`)

This branch represents a comprehensive enhancement of the original
AIFitnessSummary script, adding persistent storage, email delivery, goal
tracking, trend analysis, recommendation lifecycle management, an evidence
base, and automated scheduling.

---

### Added

#### Stage 1A — Database Layer

- **`db_client.py`**: SQLite-backed persistence layer (`DatabaseClient` class)
  with a 5-table schema covering goals, reviews, per-day metrics history,
  recommendations, and a knowledge cache. Exposed via a module-level singleton
  (`get_db()`). Schema is auto-created on first run with `CREATE TABLE IF NOT
  EXISTS`, making setup zero-touch.

#### Stage 1B — Email Delivery

- **`email_client.py`**: Gmail SMTP delivery via SSL (port 465). Converts
  Markdown reports to styled HTML using the `markdown` and `beautifulsoup4`
  libraries. Exposes `get_email_client()` which returns `None` and silently
  skips sending if any required environment variable is absent, preventing
  crashes in environments where email is not configured.

#### Stage 1C — Garmin Data Audit

- **`GARMIN_AUDIT.md`**: Comprehensive audit of every metric available through
  the `garminconnect` library, cross-referenced against what was being collected
  in the original script. Identified gaps and defined the expanded collection
  set implemented in the new `GarminClient`.

- **`garmin_client.py`** (new version): Full replacement of the original Garmin
  data fetching. Adds: sleep stage breakdown (deep/REM/light/awake), stress,
  body battery, HRV (daily status + weekly average), SpO2 (average + lowest),
  respiration rate (waking + sleeping), training readiness, training load, VO2max
  with fitness age, and body composition (weight, BMI, body fat, muscle mass).
  Implements OAuth token caching to `~/.garminconnect` (interactive MFA only on
  first run), and exponential-backoff retry on rate-limit errors.

#### Stage 2A — Goal System

- **`goal_manager.py`**: `GoalManager` class providing:
  - Interactive CLI wizard (`run_wizard()`) — 8 questions covering objective,
    weight, timeline, workouts, steps, sleep, and free-text notes. Claude
    parses the free-form answers into a structured JSON goal object.
  - AI-assisted provisional goal inference (`infer_provisional_goal()`) from
    raw metrics when no goal exists and the session is interactive.
  - Goal formatting for Claude prompt injection (`format_goal_for_prompt()`).
  - DB persistence via `db_client.DatabaseClient`.

#### Stage 2B — Goal-Aware Analysis

- **`claude_analyzer.py`**: Updated system prompt instructs Claude to frame
  every section of its analysis relative to the user's active goal. Includes
  explicit rules for on-track vs off-track metric commentary, handling of
  provisional (AI-inferred) goals, and the structured `---RECOMMENDATIONS---`
  block format. Also adds `parse_recommendations()` static method for
  extracting structured recommendations from the narrative.

#### Stage 3A — Trend Analysis

- **`trend_analyzer.py`**: `TrendAnalyzer` class that:
  - Saves review snapshots to the `reviews` and `metrics_history` DB tables
    after each run (`save_review()`).
  - Retrieves the last N reviews (default 6) and formats a trend context string
    for injection into Claude prompts (`get_trend_context()`), showing direction
    (up/down/stable) for key metrics across recent periods.

#### Stage 3B — Recommendation Tracking

- **`recommendation_tracker.py`**: `RecommendationTracker` class managing the
  full recommendation lifecycle:
  - `save_from_response()` — parses Claude's structured recommendations block
    and saves HIGH/MEDIUM priority items to the DB.
  - `get_active_for_prompt()` — retrieves active recommendations for injection
    into the next review's prompt, so Claude can follow up on previous items.
  - `process_followup()` — searches the new narrative for resolution keywords
    near each active recommendation and updates DB status accordingly.
  - `format_followup_summary()` — formats the resolution results as a report
    section.

#### Stage 3C — Report Enhancements

- **`report_generator.py`**: Three new sections added to each report:
  - **Active Goal** — displays the current goal at the top of the report.
  - **Trend Summary** — shows the formatted historical trend context string.
  - **Recommendation Follow-up** — displays which previous recommendations were
    resolved, escalated, or remain active this cycle.

#### Stage 4A — Knowledge Base

- **`knowledge_base/`**: Five curated Markdown reference files covering the
  evidence base most relevant to recreational fitness:
  - `cardiovascular.md` — VO2max norms, heart rate zones, aerobic adaptations
  - `hrv_interpretation.md` — autonomic nervous system, HRV ranges, training
    readiness interpretation
  - `recovery.md` — recovery timescales, physiological mechanisms, practical
    strategies
  - `sleep_science.md` — sleep architecture, stage functions, fitness impacts
  - `strength_training.md` — progressive overload, volume landmarks,
    periodisation, hypertrophy mechanisms

- **`knowledge_client.py`**: `get_knowledge_context()` function that selects
  up to 2 relevant knowledge base topics based on the current metrics (e.g.
  low HRV triggers `hrv` + `recovery`; workouts present triggers
  `strength_training`) and returns the file contents as a formatted prompt
  block (`[KNOWLEDGE BASE — TOPIC]`).

#### Stage 4B — Research Integration

- **`knowledge_client.py`** (extended): `get_research_context()` function adds
  live PubMed API queries and examine.com scraping relevant to the user's goal
  and current metrics. Results are cached in the `knowledge_cache` DB table
  with a 30-day TTL to avoid redundant network requests and respect rate limits.

#### Stage 6A — Integration

- **`main.py`**: Full pipeline wiring connecting all modules in the correct
  sequence. The `run_review()` function now:
  1. Loads the active goal from DB
  2. Fetches trend context (last 6 reviews)
  3. Fetches active recommendations for follow-up injection
  4. Fetches Garmin data
  5. Fetches and summarises Hevy data
  6. Selects knowledge base topics and fetches research context
  7. Calls `ClaudeAnalyzer.generate_review()` with all context
  8. Parses and saves recommendations from the response
  9. Processes recommendation follow-up and formats summary
  10. Strips the recommendations block from the narrative
  11. Assembles the full Markdown report via `ReportGenerator`
  12. Updates the review DB record with the report file path
  13. Sends the report via email

  Added `goals` subcommand to CLI to launch the goal wizard directly.

- **`scheduler.py`**: Scheduling module with two modes:
  - Daemon mode: in-process scheduling loop using the `schedule` library.
    Weekly reviews every Monday at 07:00; monthly reviews on the 1st at 07:00.
  - Cron mode: installs/removes system crontab entries via `crontab -l` /
    `crontab -`, tagged with `# AIFitnessSummary` for clean management.
  - Catch-up logic: on daemon startup, checks whether a review was missed in
    the last 48 hours and runs it immediately if so.

#### Stage 6B — Test Suite

- **`tests/conftest.py`**: Shared pytest fixtures — in-memory SQLite DB,
  sample Garmin data dict, sample Hevy summary dict, sample goal dict.
- **`tests/test_db_client.py`**: Unit tests for all `DatabaseClient` methods
  covering goals, reviews, metrics history, recommendations, and knowledge cache.
- **`tests/test_email_client.py`**: Tests for Markdown-to-HTML conversion and
  SMTP send logic (SMTP mocked).
- **`tests/test_goal_manager.py`**: Tests for goal wizard prompt building,
  JSON parsing, and goal formatting.
- **`tests/test_knowledge_client.py`**: Tests for topic selection heuristics
  and knowledge context formatting.
- **`tests/test_recommendation_tracker.py`**: Tests for recommendation parsing,
  saving, follow-up processing, and status updates.
- **`tests/test_trend_analyzer.py`**: Tests for review snapshot saving and
  trend context string generation.

#### Stage 6C — Documentation

- **`README.md`**: Comprehensive setup and usage guide covering installation,
  environment variable reference, Gmail App Password step-by-step, first-run
  goal setup, manual and automated review usage, report structure, data sources,
  architecture overview, troubleshooting, and data privacy.
- **`CHANGELOG.md`**: This file — full record of all additions and changes.
- **`ARCHITECTURE.md`**: Technical reference covering the module overview,
  full database schema, review pipeline flow, Claude prompt structure,
  knowledge base topic list, and scheduling behaviour.

---

### Changed

- **`garmin_client.py`**: Entirely rewritten. Original script used a minimal
  inline data fetch; replaced with a structured `GarminClient` class covering
  12 distinct metric categories, token caching, and rate-limit retry.
- **`claude_analyzer.py`**: System prompt significantly extended with goal-aware
  analysis instructions, recommendation format specification, and evidence-based
  guidance instructions. Added `parse_recommendations()` and
  `strip_recommendations_block()` static methods.
- **`report_generator.py`**: Updated `generate()` signature to accept `goal`,
  `trend_context_str`, and `followup_summary_str`. Added three new report
  sections (Active Goal, Trend Summary, Recommendation Follow-up).
- **`.env.example`**: Expanded with descriptive comments for all variables and
  a note on obtaining each credential.

---

### Dependencies Added

The following packages were added to `requirements.txt`:

| Package | Version | Purpose |
|---------|---------|---------|
| `schedule` | >=1.2.0 | In-process scheduling loop for daemon mode |
| `markdown` | >=3.7 | Markdown-to-HTML conversion for email reports |
| `beautifulsoup4` | >=4.12 | HTML parsing for examine.com research scraping |
| `lxml` | >=5.0 | HTML parser backend for BeautifulSoup |

Pre-existing dependencies retained:

| Package | Purpose |
|---------|---------|
| `garminconnect` | Garmin Connect API client |
| `anthropic` | Anthropic Claude API client |
| `requests` | HTTP client for Hevy API and research fetching |
| `python-dotenv` | `.env` file loading |

---

## Previous (Original Version)

The original AIFitnessSummary script was a single-file (or minimal multi-file)
tool that:

- Authenticated with Garmin Connect and fetched a basic set of daily metrics
  (primarily steps, sleep, and heart rate).
- Called the Anthropic API with a simple prompt containing the raw metrics.
- Printed or saved the Claude narrative as a text or Markdown file.
- Had no persistence, no email delivery, no goal tracking, no scheduling,
  and no recommendation management.
