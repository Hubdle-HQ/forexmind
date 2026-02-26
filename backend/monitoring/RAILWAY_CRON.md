# Railway Cron — 6am AEST Daily Refresh

## Setup

1. In Railway, add a **new service** to the same project (or use an existing cron service).
2. Use the same repo and root directory as the web service.
3. Set **Start Command** to:
   ```
   cd backend && python -m scripts.run_daily_refresh
   ```
4. In **Settings** → **Cron Schedule**, set:
   ```
   0 20 * * *
   ```
   (8pm UTC = 6am AEST next day)

5. Ensure the cron service has the same env vars as the web service (Supabase, OANDA, SMTP, etc.).

## Alternative: HTTP trigger

If you prefer to call the endpoint instead:

- Use a cron service that runs: `curl -X POST https://your-app.up.railway.app/run-daily-refresh`
- Or use an external cron (cron-job.org, GitHub Actions) to POST to `/run-daily-refresh`.
