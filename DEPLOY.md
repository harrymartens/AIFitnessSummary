# Deploying with GitHub Actions

This guide sets up automated weekly and monthly fitness reviews using GitHub
Actions — no server, no VPS, no cron jobs to maintain.

## How It Works

- **Weekly reviews** run every Monday at 07:00 UTC
- **Monthly reviews** run on the 1st of each month at 07:00 UTC
- Reports are emailed to you and committed back to the repo
- The SQLite database (`fitness_memory.db`) persists in the repo between runs
- You can also trigger a review manually from the Actions tab

## Setup (One-Time)

### 1. Complete the initial Garmin login locally

Garmin requires a one-time MFA verification (6-digit email code). Run locally:

```bash
pip install -r requirements.txt
cp .env.example .env
# Fill in .env with your credentials
python main.py --period weekly
```

Enter the MFA code when prompted. This creates cached OAuth tokens at
`~/.garminconnect` that last ~1 year.

### 2. Export Garmin tokens for GitHub Actions

```bash
bash export_garmin_tokens.sh
```

Copy the base64 output string.

### 3. Add GitHub repository secrets

Go to your repo → **Settings → Secrets and variables → Actions** and add:

| Secret Name          | Value                                          |
|----------------------|------------------------------------------------|
| `GARMIN_EMAIL`       | Your Garmin Connect email                      |
| `GARMIN_PASSWORD`    | Your Garmin Connect password                   |
| `GARMIN_TOKENS_B64`  | Base64 string from step 2                      |
| `HEVY_API_KEY`       | From https://hevy.com/settings?developer       |
| `ANTHROPIC_API_KEY`  | From https://console.anthropic.com/settings/keys |
| `EMAIL_SENDER`       | Your Gmail address                             |
| `EMAIL_RECIPIENT`    | Where to receive reports                       |
| `GMAIL_APP_PASSWORD` | 16-char Gmail App Password (see .env.example)  |

### 4. Push to GitHub

```bash
git add .
git commit -m "Add GitHub Actions workflow for automated fitness reviews"
git push
```

### 5. Test it

Go to **Actions → Fitness Review → Run workflow** and select a period. Check
your email for the report.

## Adjusting the Schedule

Edit `.github/workflows/fitness-review.yml` and change the cron expressions:

```yaml
schedule:
  - cron: "0 7 * * 1"    # Weekly: Monday 7am UTC
  - cron: "0 7 1 * *"    # Monthly: 1st of month 7am UTC
```

All times are UTC. To convert, e.g. 7am AEST = 9pm UTC previous day (`0 21 * * 0`).

## Maintenance

### Token refresh (~once per year)

If reviews start failing with Garmin auth errors:

1. Run `python main.py --period weekly` locally to re-authenticate
2. Run `bash export_garmin_tokens.sh`
3. Update the `GARMIN_TOKENS_B64` secret in GitHub

### Viewing history

All reports are committed to the `reports/` directory. The SQLite database
`fitness_memory.db` tracks goals, review history, recommendations, and trends
across all runs.
