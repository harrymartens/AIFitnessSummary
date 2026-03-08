# Deploying with GitHub Actions + Supabase

This guide sets up automated weekly and monthly fitness reviews using GitHub
Actions and a free Supabase database — no server, no VPS, no cron jobs.

## How It Works

- **Weekly reviews** run every Monday at 07:00 UTC
- **Monthly reviews** run on the 1st of each month at 07:00 UTC
- Reports are emailed to you automatically
- All data (goals, reviews, recommendations, trends) persists in Supabase
- You can trigger a review manually from the Actions tab anytime

## Setup (One-Time)

### 1. Create a free Supabase project

1. Go to [supabase.com](https://supabase.com) and create a free account
2. Create a new project (any name, e.g. "fitness-summary")
3. Choose a region close to you and set a database password
4. Once created, go to **Settings → Database → Connection string → URI**
5. Copy the connection string — it looks like:
   ```
   postgresql://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres
   ```
6. Replace `[password]` with the database password you set

The app automatically creates all required tables on first run.

### 2. Complete the initial Garmin login locally

Garmin requires a one-time MFA verification (6-digit email code). Run locally:

```bash
pip install -r requirements.txt
cp .env.example .env
# Fill in .env with your credentials (including DATABASE_URL from step 1)
python main.py --period weekly
```

Enter the MFA code when prompted. This creates cached OAuth tokens at
`~/.garminconnect` that last ~1 year.

### 3. Export Garmin tokens for GitHub Actions

```bash
bash export_garmin_tokens.sh
```

Copy the base64 output string.

### 4. Add GitHub repository secrets

Go to your repo → **Settings → Secrets and variables → Actions** and add:

| Secret Name          | Value                                            |
|----------------------|--------------------------------------------------|
| `DATABASE_URL`       | Supabase connection string from step 1           |
| `GARMIN_EMAIL`       | Your Garmin Connect email                        |
| `GARMIN_PASSWORD`    | Your Garmin Connect password                     |
| `GARMIN_TOKENS_B64`  | Base64 string from step 3                        |
| `HEVY_API_KEY`       | From https://hevy.com/settings?developer         |
| `ANTHROPIC_API_KEY`  | From https://console.anthropic.com/settings/keys |
| `EMAIL_SENDER`       | Your Gmail address                               |
| `EMAIL_RECIPIENT`    | Where to receive reports                         |
| `GMAIL_APP_PASSWORD` | 16-char Gmail App Password (see .env.example)    |

### 5. Push to GitHub

```bash
git add .
git commit -m "Add GitHub Actions workflow for automated fitness reviews"
git push
```

### 6. Test it

Go to **Actions → Fitness Review → Run workflow** and select a period. Check
your email for the report.

## Local Development

For local development, you can use either backend:

- **Supabase**: Set `DATABASE_URL` in `.env` to your connection string
- **SQLite**: Leave `DATABASE_URL` unset — uses local `fitness_memory.db`

Both backends share the same schema and API. Your local SQLite database and
Supabase are independent — data does not sync between them.

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

### Viewing your data

- **Email reports**: Delivered to your inbox on schedule
- **Supabase dashboard**: Browse your data at supabase.com → Table Editor
- **Local reports**: Run locally with `python main.py --period weekly` for
  on-demand reviews saved to `reports/`
