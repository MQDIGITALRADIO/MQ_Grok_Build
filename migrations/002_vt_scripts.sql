-- M2: Voice track / AI announcer scripts

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS vt_scripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    log_event_id INTEGER NOT NULL UNIQUE REFERENCES log_events(id) ON DELETE CASCADE,
    variation TEXT NOT NULL,
    script_text TEXT NOT NULL,
    daypart TEXT,
    style TEXT DEFAULT 'warm',
    station_name TEXT NOT NULL DEFAULT 'MQ Digital',
    status TEXT NOT NULL DEFAULT 'DRAFT',
    source TEXT NOT NULL DEFAULT 'AI_TEMPLATE',
    prev_title TEXT,
    prev_artist TEXT,
    next_title TEXT,
    next_artist TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_vt_scripts_status ON vt_scripts(status);
CREATE INDEX IF NOT EXISTS idx_vt_scripts_event ON vt_scripts(log_event_id);
