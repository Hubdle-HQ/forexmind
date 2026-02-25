-- Run this in Supabase SQL Editor after schema.sql
-- Required for vector similarity search in ingest.retrieve_documents()
-- Note: query_embedding is text to avoid PostgREST vector serialization issues.
-- Pass embedding as string '[0.1,0.2,...]' from Python.

-- Drop old overload if it exists (vector param) to avoid PGRST203 ambiguity
DROP FUNCTION IF EXISTS match_forex_documents(vector(1536), float, int);

CREATE OR REPLACE FUNCTION match_forex_documents(
    query_embedding text,
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
LANGUAGE plpgsql
AS $$
BEGIN
    -- With few rows (e.g. <100), IVFFlat lists=100 can return empty. Search all cells.
    SET LOCAL ivfflat.probes = 100;
    RETURN QUERY
    SELECT
        fd.id,
        fd.content,
        fd.metadata,
        fd.source,
        1 - (fd.embedding <=> query_embedding::vector(1536)) AS similarity
    FROM forex_documents fd
    WHERE fd.embedding IS NOT NULL
    ORDER BY fd.embedding <=> query_embedding::vector(1536)
    LIMIT LEAST(match_count, 200);
END;
$$;
