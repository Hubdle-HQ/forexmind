# Database migrations

Run migrations in the Supabase SQL Editor (Dashboard → SQL Editor).

1. **001_add_langfuse_trace_id.sql** — Adds `langfuse_trace_id` to `signal_outcomes` for Langfuse score logging.
2. **002_add_risk_reward.sql** — Adds `risk_reward` to `signal_outcomes` for R:R display.
3. **003_add_signal_rejections.sql** — Creates `signal_rejections` table for tracking gate failures (evaluation).
