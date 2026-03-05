-- Create signal_rejections table for tracking pipeline runs that failed the quality gate.
-- Enables evaluation: rejection distribution, threshold tuning, setup quality analysis.

CREATE TABLE IF NOT EXISTS signal_rejections (
    id bigserial PRIMARY KEY,
    rejected_at timestamptz DEFAULT now(),
    pair text NOT NULL,
    rejection_reason text NOT NULL,  -- macro_gate | technical_quality_gate | error_gate | claude_no_trade
    rejection_details text,
    macro_sentiment text,
    macro_confidence numeric,
    technical_quality numeric,
    technical_setup text,
    technical_direction text,
    technical_context jsonb,
    error_message text,
    langfuse_trace_id text
);

CREATE INDEX IF NOT EXISTS signal_rejections_rejected_at_idx ON signal_rejections (rejected_at);
CREATE INDEX IF NOT EXISTS signal_rejections_pair_idx ON signal_rejections (pair);
CREATE INDEX IF NOT EXISTS signal_rejections_rejection_reason_idx ON signal_rejections (rejection_reason);
