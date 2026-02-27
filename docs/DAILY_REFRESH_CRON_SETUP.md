# Daily Refresh — External Cron Setup (Option 2)

Runs the daily refresh (scrapers, RAG ingest, signal evaluator, health check, RAGAS on Sundays) every 24 hours at 20:00 UTC (6am AEST).

---

## Option A: GitHub Actions (Recommended — Zero Config)

**Already set up.** Push this repo to GitHub and enable Actions.

1. Push the repo to GitHub (if not already).
2. Go to **Actions** tab → workflow **Daily Refresh**.
3. It runs automatically at 20:00 UTC daily.
4. To run manually: **Actions** → **Daily Refresh** → **Run workflow**.

**Custom URL:** In repo **Settings** → **Secrets and variables** → **Actions** → **Variables**, add `DAILY_REFRESH_URL` (e.g. `https://your-app.up.railway.app`) to override the default.

---

## Option B: cron-job.org (Free)

1. Sign up at [cron-job.org](https://cron-job.org) (free).
2. **Create cron job**:
   - **Title:** ForexMind Daily Refresh
   - **URL:** `https://forexmind-production.up.railway.app/run-daily-refresh`
   - **Request method:** POST
   - **Schedule:** Every day at 20:00 UTC
     - Or use cron: `0 20 * * *`
3. Save. Done.

---

## Verify It Works

After the next run (or trigger manually):

- Check Railway logs for `/run-daily-refresh` requests.
- Or call manually: `curl -X POST https://forexmind-production.up.railway.app/run-daily-refresh`
