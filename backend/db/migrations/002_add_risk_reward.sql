-- Add risk_reward to signal_outcomes for R:R display (Week 4).
ALTER TABLE signal_outcomes ADD COLUMN IF NOT EXISTS risk_reward numeric;
