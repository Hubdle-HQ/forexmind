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
