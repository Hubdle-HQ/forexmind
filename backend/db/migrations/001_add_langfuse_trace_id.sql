-- Add langfuse_trace_id to signal_outcomes for Langfuse score logging.
-- Run in Supabase SQL Editor.
ALTER TABLE signal_outcomes ADD COLUMN IF NOT EXISTS langfuse_trace_id text;
