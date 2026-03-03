-- 1. Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Create forex_documents table
CREATE TABLE forex_documents (
    id bigserial PRIMARY KEY,
    content text NOT NULL,
    metadata jsonb DEFAULT '{}',
    embedding vector(1536),
    source text,
    is_stale boolean DEFAULT false,
    created_at timestamptz DEFAULT now(),
    last_verified timestamptz DEFAULT now()
);

-- 3. Create IVFFlat index on forex_documents.embedding
CREATE INDEX ON forex_documents USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- 4. Create agent_cache table
CREATE TABLE agent_cache (
    cache_key text PRIMARY KEY,
    result jsonb NOT NULL,
    cached_at timestamptz DEFAULT now(),
    expires_at timestamptz
);

-- 5. Create user_trades table
CREATE TABLE user_trades (
    id bigserial PRIMARY KEY,
    user_id uuid,
    pair text,
    direction text,
    entry_price numeric,
    exit_price numeric,
    pips_result numeric,
    outcome text,
    session text,
    setup_type text,
    traded_at timestamptz,
    notes text
);

-- 6. Create pipeline_health table
CREATE TABLE pipeline_health (
    id bigserial PRIMARY KEY,
    source text,
    status text,
    error_msg text,
    checked_at timestamptz DEFAULT now()
);

-- 7. Create signal_outcomes table
CREATE TABLE signal_outcomes (
    id bigserial PRIMARY KEY,
    signal_id uuid,
    pair text,
    direction text,
    entry numeric,
    tp numeric,
    sl numeric,
    hit_tp boolean,
    hit_sl boolean,
    pips_result numeric,
    generated_at timestamptz,
    resolved_at timestamptz
);

-- 8. Create eval_results table
CREATE TABLE eval_results (
    id bigserial PRIMARY KEY,
    week text,
    context_relevancy numeric,
    faithfulness numeric,
    answer_relevancy numeric,
    created_at timestamptz DEFAULT now()
);

-- 9. Enable Row Level Security on user_trades table only
ALTER TABLE user_trades ENABLE ROW LEVEL SECURITY;

-- 10. Week 5A: technical_context on signal_outcomes (run in Supabase SQL editor)
ALTER TABLE signal_outcomes
ADD COLUMN IF NOT EXISTS technical_context JSONB;

-- 11. Week 5A: pattern_outcomes table for pattern memory storage
CREATE TABLE IF NOT EXISTS pattern_outcomes (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_outcomes_id   BIGINT REFERENCES signal_outcomes(id) ON DELETE CASCADE,
    pair                 TEXT NOT NULL,
    direction            TEXT NOT NULL,
    setup                TEXT NOT NULL,
    session              TEXT NOT NULL,
    d1_bias              TEXT,
    h4_structure         TEXT,
    timeframe_alignment  TEXT,
    rsi_zone             TEXT,
    ema_trend            TEXT,
    structure_bias       TEXT,
    broke_asian_range    TEXT,
    atr_used             FLOAT,
    entry_price          FLOAT NOT NULL,
    stop_loss            FLOAT NOT NULL,
    take_profit          FLOAT NOT NULL,
    risk_reward          FLOAT NOT NULL,
    outcome              TEXT,
    pips_result          FLOAT,
    hit_tp               BOOLEAN,
    hit_sl               BOOLEAN,
    embedding            vector(1536),
    pattern_text         TEXT NOT NULL,
    created_at           TIMESTAMPTZ DEFAULT NOW(),
    resolved_at          TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS pattern_outcomes_embedding_idx
ON pattern_outcomes
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 50);

CREATE INDEX IF NOT EXISTS pattern_outcomes_pair_direction_idx
ON pattern_outcomes (pair, direction, outcome);
