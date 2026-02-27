# Daily Refresh Cron — Setup Options

Runs at **20:00 UTC** (6am AEST next day): scrapers, RAG ingest, signal evaluator, health check, RAGAS (Sundays only).

---

## Option 1: External Cron (Recommended — Free)

See **[docs/DAILY_REFRESH_CRON_SETUP.md](../../docs/DAILY_REFRESH_CRON_SETUP.md)** for:

- **GitHub Actions** — Already configured in `.github/workflows/daily-refresh.yml`. Push to GitHub and enable Actions.
- **cron-job.org** — Free. POST to `https://forexmind-production.up.railway.app/run-daily-refresh` daily.

---

## Option 2: Railway Cron Service (Paid)

1. Add a **new service** to the same project.
2. **Start Command:** `cd backend && python -m scripts.run_daily_refresh`
3. **Cron Schedule:** `0 20 * * *`
4. Same env vars as the web service.
