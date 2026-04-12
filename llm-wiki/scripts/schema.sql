-- llm-wiki index schema
-- Compatible with PGlite (via Node sidecar) and native Postgres.
-- Default embedding dimension: 384 (all-MiniLM-L6-v2).
-- For OpenAI (1536 dims): ALTER TABLE content_chunks ALTER COLUMN embedding TYPE vector(1536);

CREATE EXTENSION IF NOT EXISTS vector;
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'pg_trgm not available — fuzzy title matching disabled';
END $$;

CREATE TABLE IF NOT EXISTS pages (
    slug            TEXT PRIMARY KEY,
    type            TEXT NOT NULL,
    title           TEXT NOT NULL,
    compiled_truth  TEXT NOT NULL DEFAULT '',
    timeline        TEXT NOT NULL DEFAULT '',
    frontmatter     JSONB NOT NULL DEFAULT '{}'::jsonb,
    content_hash    TEXT NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    search_vector   TSVECTOR
);

CREATE INDEX IF NOT EXISTS pages_type_idx         ON pages (type);
CREATE INDEX IF NOT EXISTS pages_frontmatter_idx  ON pages USING GIN (frontmatter);
CREATE INDEX IF NOT EXISTS pages_search_idx       ON pages USING GIN (search_vector);
DO $$
BEGIN
    CREATE INDEX IF NOT EXISTS pages_title_trgm_idx ON pages USING GIN (title gin_trgm_ops);
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'pg_trgm index skipped — not available in this environment';
END $$;

-- Trigger to maintain search_vector
CREATE OR REPLACE FUNCTION pages_search_trigger() RETURNS trigger AS $$
BEGIN
    NEW.search_vector := to_tsvector('english',
        coalesce(NEW.title, '') || ' ' ||
        coalesce(NEW.compiled_truth, '') || ' ' ||
        coalesce(NEW.timeline, '')
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS pages_search_update ON pages;
CREATE TRIGGER pages_search_update
    BEFORE INSERT OR UPDATE ON pages
    FOR EACH ROW EXECUTE FUNCTION pages_search_trigger();

CREATE TABLE IF NOT EXISTS content_chunks (
    id              BIGSERIAL PRIMARY KEY,
    page_slug       TEXT NOT NULL REFERENCES pages(slug) ON DELETE CASCADE,
    chunk_index     INT NOT NULL,
    chunk_source    TEXT NOT NULL CHECK (chunk_source IN ('compiled_truth', 'timeline')),
    chunk_text      TEXT NOT NULL,
    embedding       VECTOR(384)
);

CREATE INDEX IF NOT EXISTS content_chunks_page_idx ON content_chunks (page_slug);
CREATE INDEX IF NOT EXISTS content_chunks_hnsw
    ON content_chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS links (
    from_slug   TEXT NOT NULL REFERENCES pages(slug) ON DELETE CASCADE,
    to_slug     TEXT NOT NULL,
    link_type   TEXT NOT NULL DEFAULT 'references',
    PRIMARY KEY (from_slug, to_slug, link_type)
);

CREATE INDEX IF NOT EXISTS links_to_idx ON links (to_slug);

CREATE TABLE IF NOT EXISTS tags (
    page_slug   TEXT NOT NULL REFERENCES pages(slug) ON DELETE CASCADE,
    tag         TEXT NOT NULL,
    PRIMARY KEY (page_slug, tag)
);

CREATE TABLE IF NOT EXISTS timeline_entries (
    id          BIGSERIAL PRIMARY KEY,
    page_slug   TEXT NOT NULL REFERENCES pages(slug) ON DELETE CASCADE,
    entry_date  DATE NOT NULL,
    summary     TEXT NOT NULL,
    detail      TEXT
);

CREATE INDEX IF NOT EXISTS timeline_page_date_idx ON timeline_entries (page_slug, entry_date DESC);
