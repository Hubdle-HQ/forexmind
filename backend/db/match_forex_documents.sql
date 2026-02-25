-- Run this in Supabase SQL Editor after schema.sql
-- Required for vector similarity search in ingest.retrieve_documents()

CREATE OR REPLACE FUNCTION match_forex_documents(
    query_embedding vector(1536),
    match_threshold float DEFAULT 0,
    match_count int DEFAULT 5
)
RETURNS TABLE (
    id bigint,
    content text,
    metadata jsonb,
    source text,
    similarity float
)
LANGUAGE sql
AS $$
    SELECT
        fd.id,
        fd.content,
        fd.metadata,
        fd.source,
        1 - (fd.embedding <=> query_embedding) AS similarity
    FROM forex_documents fd
    WHERE fd.embedding IS NOT NULL
    ORDER BY fd.embedding <=> query_embedding
    LIMIT LEAST(match_count, 200);
$$;
