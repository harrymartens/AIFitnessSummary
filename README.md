# AIFitnessSummary

AI-powered personal fitness review system combining Garmin health data, Hevy
strength training records, and Claude AI analysis into weekly and monthly
reports delivered to your email.

## Features

- **Automated reviews** — weekly (Monday 7am) and monthly (1st, 7am) generation
- **Email delivery** — styled HTML reports via Gmail SMTP
- **Goal tracking** — AI-assisted goal setup with progress monitoring each review
- **Historical memory** — trend analysis across the last 6 reviews
- **Recommendation lifecycle** — actionable items tracked and followed up each cycle
- **Evidence-based insights** — curated fitness knowledge base + PubMed research
- **Garmin integration** — full health metrics suite (steps, sleep, HRV, VO2max, etc.)
- **Hevy integration** — strength training volume, PRs, exercise breakdown

## Requirements

- Python 3.11+
- Garmin Connect account (any Garmin device)
- Hevy app account with a Pro subscription (required for API access)
- Anthropic API key
- Gmail account with App Password enabled

## Installation

### 1. Clone and install dependencies

```bash
git clone <repo>
cd AIFitnessSummary
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
# Edit .env with your credentials — see the reference table below
```

### 3. Environment variables reference

| Variable | Required | Description |
|----------|----------|-------------|
| `GARMIN_EMAIL` | Yes | Email address used to log in to Garmin Connect |
| `GARMIN_PASSWORD` | Yes | Password for your Garmin Connect account |
| `HEVY_API_KEY` | Yes | API key from Hevy app (Settings → Developer). Requires Hevy Pro. |
| `ANTHROPIC_API_KEY` | Yes | API key from [platform.claude.com](https://platform.claude.com/settings/keys) |
| `EMAIL_SENDER` | Yes | Gmail address to send reports from (must match the App Password) |
| `EMAIL_RECIPIENT` | Yes | Address to receive reports (can be the same as `EMAIL_SENDER`) |
| `GMAIL_APP_PASSWORD` | Yes | 16-character App Password generated in your Google Account security settings |
| `DB_PATH` | No | Path to the SQLite database file (default: `fitness_memory.db` in project root) |

### 4. Gmail App Password setup

Gmail requires an App Password rather than your normal account password when
connecting via SMTP. Here is how to generate one:

1. Go to your [Google Account](https://myaccount.google.com) and sign in.
2. Navigate to **Security** in the left sidebar.
3. Under "How you sign in to Google", click **2-Step Verification** and make
   sure it is turned on. App Passwords are not available without 2-Step
   Verification enabled.
4. Return to the Security page and search for **App Passwords** (or go directly
   to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)).
5. Click **Create a new app password**. Give it a name such as "AIFitnessSummary".
6. Google will display a 16-character password in four groups of four letters
   (e.g. `abcd efgh ijkl mnop`). Copy it immediately — it will not be shown again.
7. Paste the password into your `.env` file as `GMAIL_APP_PASSWORD`, with or
   without the spaces (both formats work).

If you receive an "Authentication failed" error when sending, double-check that:
- The `EMAIL_SENDER` address matches the Google account that owns the App Password.
- You are using the App Password, not your regular Gmail password.
- 2-Step Verification is still active on the account.

### 5. First run — set up your fitness goal

```bash
python main.py goals
```

This launches an interactive wizard that asks about your primary fitness goal,
weight targets, activity targets, timeline, and any other context. Claude
analyses your answers and creates a structured goal object stored in the local
database. The goal is then referenced in every subsequent review — Claude frames
all observations relative to it.

Re-run `python main.py goals` at any time to update your goal.

## Usage

### Manual reviews

```bash
python main.py --period weekly    # Generate a review covering the last 7 days
python main.py --period monthly   # Generate a review covering the last 30 days
```

The report is saved as a Markdown file under `reports/` and emailed if the
email variables are configured. The review period always ends on yesterday
(the last complete day of data).

### Automatic scheduling

#### Daemon mode (runs continuously)

```bash
python scheduler.py
```

Keeps a scheduling loop running in the foreground. Weekly reviews fire every
Monday at 07:00; monthly reviews fire on the 1st of each month at 07:00.
Stop it with Ctrl+C.

#### Cron mode (system crontab)

```bash
python scheduler.py install-cron        # Add entries to your crontab
python scheduler.py install-cron --dry-run  # Preview what would be added
python scheduler.py remove-cron         # Remove the entries
python scheduler.py show-cron           # Print the cron lines without installing
```

Cron entries are tagged with `# AIFitnessSummary` so they can be cleanly
identified and removed later.

#### Catch-up behaviour

If the machine was off at a scheduled time, the scheduler checks on startup
whether a review was missed within the previous 48 hours. If so, it runs the
missed review immediately before entering the normal schedule loop. This window
covers:

- Weekly: if today is Tuesday or Wednesday and the Monday 07:00 run was missed
- Monthly: if today is the 2nd or 3rd and the 1st 07:00 run was missed

### Goal management

```bash
python main.py goals
```

Launches the interactive goal wizard. If a previous goal exists, the new one
replaces it (the old goal is deactivated rather than deleted). Goals are stored
in `fitness_memory.db` and persist between runs.

## Report structure

Each generated report contains the following sections:

| Section | Contents |
|---------|----------|
| Header | Review period, generation timestamp, data sources |
| Active Goal | Your current fitness goal displayed at the top of every report |
| Trend Summary | Direction of key metrics compared to your last 6 reviews |
| Recommendation Follow-up | Status of previous recommendations (resolved / still active) |
| Garmin data tables | Raw metric tables: steps, sleep stages, HRV, stress, body battery, SpO2, VO2max, body composition, respiration, training readiness |
| Hevy data tables | Workout count, total volume, volume by muscle group, exercise breakdown, personal records |
| Executive Summary | Claude's top-level assessment of the period |
| Activity & Cardiovascular Highlights | Analysis of steps, distance, intensity minutes, VO2max trends |
| Sleep Quality | Sleep stage breakdown and recovery implications |
| Recovery & Stress | HRV, stress, body battery, and readiness interpretation |
| Strength Training Analysis | Volume, frequency, PRs, and muscle balance assessment |
| Training Load Assessment | Overall load status and progression commentary |
| Recommendations for Next Period | 3–5 specific, prioritised, actionable items |

## Data sources

### Garmin Connect

The following metrics are collected for each review period:

- **Steps & activity** — daily step count, active minutes (moderate + vigorous), intensity minutes, total calories, floors climbed, distance
- **Heart rate** — average resting heart rate, daily trend
- **Sleep** — nightly total sleep, deep sleep, REM sleep, light sleep, and awake time (in hours)
- **Stress** — average daily stress score (Garmin 0–100 scale)
- **Body battery** — daily charged and drained values
- **HRV** — daily status, last-night average (ms), weekly average (ms)
- **SpO2** — average and lowest blood oxygen saturation per day
- **Respiration** — average waking and sleeping breathing rate (breaths/min)
- **Training readiness** — daily readiness score and qualitative level
- **Training load** — daily training load values and latest status (e.g. "Low", "Optimal")
- **VO2max** — latest VO2max estimate and fitness age (fetched for end of period)
- **Body composition** — weight (kg), BMI, body fat percentage, muscle mass (from Garmin scale if available)
- **Running activities** — total run distance (km) for the period

### Hevy

The following metrics are computed from Hevy workout records:

- **Workout count** — number of sessions in the period
- **Workouts per week** — frequency normalised to a 7-day rate
- **Workout dates** — list of dates with training activity
- **Volume by muscle group** — total sets × reps × weight (kg) broken down by primary muscle group
- **Exercise breakdown** — per-exercise summary of sets, reps, and max weight
- **Personal records** — exercises where a new max weight was recorded within the period

## Architecture overview

| Module | Role |
|--------|------|
| `main.py` | Entry point, CLI argument parsing, review pipeline orchestration |
| `config.py` | Constants (model name, date format, report directory, valid periods) and date-range helper |
| `db_client.py` | SQLite persistence layer — all reads and writes to `fitness_memory.db` |
| `garmin_client.py` | Garmin Connect API client — authentication with token caching, all metric fetchers |
| `hevy_client.py` | Hevy REST API client — workout pagination, exercise template lookup, summary computation |
| `claude_analyzer.py` | Anthropic Claude integration — prompt assembly, narrative generation, recommendation parsing |
| `report_generator.py` | Markdown report assembly — data tables + Claude narrative combined into a formatted file |
| `email_client.py` | Gmail SMTP delivery — Markdown-to-HTML conversion, styled email sending |
| `goal_manager.py` | Goal wizard (interactive CLI), AI-assisted goal parsing, goal formatting for prompts |
| `trend_analyzer.py` | Historical snapshot persistence and trend context string generation |
| `recommendation_tracker.py` | Recommendation lifecycle — save from Claude response, follow-up status updates |
| `knowledge_client.py` | Curated knowledge base topic selection + PubMed/examine.com live research with SQLite caching |
| `scheduler.py` | Daemon scheduling loop and crontab management with catch-up logic |

## Troubleshooting

### Garmin MFA on first run

The first time `GarminClient` is instantiated, it performs a full credential
login and will prompt for a 6-digit verification code that Garmin emails to
you. Enter the code when prompted. OAuth tokens are then saved to
`~/.garminconnect` and reused for all subsequent runs (~1 year before they
expire). If you see MFA prompts on every run, check that `~/.garminconnect`
exists and is writable.

### Gmail App Password setup

See the [Gmail App Password setup](#4-gmail-app-password-setup) section above.
The most common issues are: 2-Step Verification is not enabled, or the password
was typed rather than pasted (the spaces in the displayed password are
cosmetic — include or exclude them).

### Hevy API rate limits

The Hevy API has a page size limit of 10 workouts per request. For long periods
or large workout histories, `fetch_workouts` paginates automatically. If you
receive `429` errors, the client does not currently implement Hevy-specific
retry logic — wait a minute and re-run.

### Missing data / `—` in reports

If a metric shows `—` in a report, it means no data was available from the API
for that metric in the review period. Common causes:
- The metric requires a specific Garmin device (e.g. pulse oximeter for SpO2,
  compatible scale for body composition).
- The device was not worn or synced during the period.
- Garmin returned an empty response for that date (this is normal for the
  training readiness endpoint on days with no prior training).

### Database errors

The SQLite database (`fitness_memory.db`) is created automatically on first
run. If you move the project directory, either update `DB_PATH` in `.env` or
move the database file alongside the code. The schema is created with
`CREATE TABLE IF NOT EXISTS`, so re-running after a missing database recreates
it cleanly (with no historical data).

## Data privacy

All data is stored locally:

- **`fitness_memory.db`** — SQLite database containing goals, review snapshots,
  daily metric history, recommendations, and knowledge cache entries.
- **`reports/`** — Generated Markdown report files, one per review run.

Data leaves the machine only when:

1. The Garmin and Hevy APIs are queried to fetch your metrics.
2. Metric data and goal context are sent to the Anthropic API for Claude to
   generate the narrative analysis.
3. The finished report is sent to your email via Gmail SMTP.

No data is sent to any other third party. The Anthropic API call includes
your fitness metrics for the review period — do not use this system if that
is a concern.
