-- M3: VT recorded audio + Segue Editor links

PRAGMA foreign_keys = ON;

ALTER TABLE vt_scripts ADD COLUMN audio_path TEXT;
ALTER TABLE vt_scripts ADD COLUMN trim_in_ms INTEGER NOT NULL DEFAULT 0;
ALTER TABLE vt_scripts ADD COLUMN trim_out_ms INTEGER;
ALTER TABLE vt_scripts ADD COLUMN recorded_at TEXT;

CREATE TABLE IF NOT EXISTS segue_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_event_id INTEGER NOT NULL REFERENCES log_events(id) ON DELETE CASCADE,
    to_event_id INTEGER NOT NULL REFERENCES log_events(id) ON DELETE CASCADE,
    vt_event_id INTEGER REFERENCES log_events(id) ON DELETE SET NULL,
    from_outro_mark_ms INTEGER NOT NULL DEFAULT 0,
    to_intro_mark_ms INTEGER NOT NULL DEFAULT 0,
    vt_in_ms INTEGER NOT NULL DEFAULT 0,
    vt_out_ms INTEGER,
    duck_db REAL NOT NULL DEFAULT -11.0,
    crossfade_ms INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(from_event_id, to_event_id)
);

CREATE INDEX IF NOT EXISTS idx_segue_from ON segue_links(from_event_id);
CREATE INDEX IF NOT EXISTS idx_segue_to ON segue_links(to_event_id);
