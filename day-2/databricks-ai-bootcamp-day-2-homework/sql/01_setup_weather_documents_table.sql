-- Setup script for weather_documents table
-- Run this manually in your Lakebase Postgres database or just call POST /weather/sync
-- the Flask app runs the same DDL via weather_db.ensure_weather_tables() on every weather request
--
-- This is the RAW document store: one row per normalized National Weather Service item
-- (an active alert, a single forecast period, or a forecaster's  Area Forecast Discussion).
-- ingest_weather_embeddings.py reads from here to compute the vectors in weather_embeddings.

-- Create the weather documents table
CREATE TABLE IF NOT EXISTS weather_documents (
    id TEXT PRIMARY KEY,
    location TEXT NOT NULL,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    state TEXT, -- 
    grid_office TEXT,
    grid_x INT,
    grid_y INT,
    source_type TEEX NOT NULL
        CHECK (source_type IN ('alert', 'forecast', 'discussion')),
    event TEXT,
    headline TEXT,
    severity TEXT,
    narrative_text TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    issued_at TIMESTAMPTZ,
    effective_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    source_url TEXT,
    payload JSONB NOT NULL,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_weather_documents_location
ON weather_documents (location);

CREATE INDEX IF NOT EXISTS idx_weather_documents_issued_at
ON weather_documents (issued_at DESC);

-- Verify the table was created
SELECT 
    table_name,
    column_name,
    data_type
FROM information_schema.columns
WHERE table_name = 'weather_documents'
ORDER BY ordinal_position;