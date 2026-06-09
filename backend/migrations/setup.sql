-- ==============================================================================
-- DataChat Storage Setup
-- ==============================================================================
-- Run this against your STORAGE database before starting the app.
--
-- Usage:
--   psql -U <your_user> -d <your_storage_db> -f migrations/setup.sql
--
-- This creates the tables needed for conversation history.
-- These tables are ONLY created in your storage database,
-- never in your target (data) database.
-- ==============================================================================

CREATE TABLE IF NOT EXISTS conversations (
    id VARCHAR(255) PRIMARY KEY,
    database_name VARCHAR(255),
    title VARCHAR(500) DEFAULT 'New Chat',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    conversation_id VARCHAR(255) REFERENCES conversations(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL,
    content TEXT,
    sql_generated TEXT,
    params_used TEXT,
    timestamp TIMESTAMP DEFAULT NOW()
);

-- Index for fast conversation message lookups
CREATE INDEX IF NOT EXISTS idx_messages_conversation_id 
    ON messages(conversation_id);

-- Index for listing conversations sorted by recency
CREATE INDEX IF NOT EXISTS idx_conversations_updated_at 
    ON conversations(updated_at DESC);

-- ==============================================================================
-- Done! You can now start the app with: uvicorn main:app --reload
-- ==============================================================================