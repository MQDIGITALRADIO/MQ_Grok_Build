-- MQ Radio Automation M1 — initial schema

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Rotation / music categories
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
    priority INTEGER NOT NULL DEFAULT 100,
    is_music INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Tracks / assets library
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    album TEXT,
    year INTEGER,
    genre TEXT,
    bpm REAL,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    intro_ms INTEGER NOT NULL DEFAULT 0,
    outro_ms INTEGER NOT NULL DEFAULT 0,
    energy INTEGER,          -- 1-10
    mood TEXT,
    gender TEXT,             -- M / F / MIX / UNKNOWN
    australian INTEGER NOT NULL DEFAULT 0,
    era TEXT,                -- e.g. 80s, 90s, 2000s
    category_id INTEGER REFERENCES categories(id),
    rotation_category TEXT,  -- Power / Recurrent / Gold etc.
    start_date TEXT,         -- ISO date when eligible
    end_date TEXT,
    last_played TEXT,
    play_count INTEGER NOT NULL DEFAULT 0,
    explicit INTEGER NOT NULL DEFAULT 0,
    file_path TEXT,
    replaygain REAL,
    isrc TEXT,
    apra_work_id TEXT,       -- optional APRA
    ppca_id TEXT,            -- optional PPCA
    event_type TEXT NOT NULL DEFAULT 'MUSIC',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tracks_artist ON tracks(artist);
CREATE INDEX IF NOT EXISTS idx_tracks_category ON tracks(category_id);
CREATE INDEX IF NOT EXISTS idx_tracks_last_played ON tracks(last_played);
CREATE INDEX IF NOT EXISTS idx_tracks_rotation ON tracks(rotation_category);

-- Clocks (hour templates)
CREATE TABLE IF NOT EXISTS clocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
    duration_sec INTEGER NOT NULL DEFAULT 3600,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Clock slots (ordered positions within a clock)
CREATE TABLE IF NOT EXISTS clock_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clock_id INTEGER NOT NULL REFERENCES clocks(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    category_id INTEGER REFERENCES categories(id),
    category_code TEXT,
    timing_mode TEXT NOT NULL DEFAULT 'FLOAT',
    chain_mode TEXT NOT NULL DEFAULT 'AUTO',
    offset_sec INTEGER,          -- optional fixed offset from hour start
    duration_sec INTEGER,        -- optional fixed duration
    label TEXT,
    UNIQUE(clock_id, position)
);

-- Station rules
CREATE TABLE IF NOT EXISTS station_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    artist_separation_minutes INTEGER NOT NULL DEFAULT 60,
    title_separation_minutes INTEGER NOT NULL DEFAULT 120,
    album_separation_minutes INTEGER NOT NULL DEFAULT 180,
    same_artist_max_per_hour INTEGER NOT NULL DEFAULT 2,
    explicit_allowed INTEGER NOT NULL DEFAULT 0,
    australian_content_min_pct INTEGER NOT NULL DEFAULT 25,
    rules_json TEXT,             -- extra daypart / energy rules
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Daily living logs (one per calendar day)
CREATE TABLE IF NOT EXISTS daily_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    log_date TEXT NOT NULL UNIQUE,  -- YYYY-MM-DD
    status TEXT NOT NULL DEFAULT 'DRAFT',
    ruleset_id INTEGER REFERENCES station_rules(id),
    generated_at TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Log events (Living Log rows)
CREATE TABLE IF NOT EXISTS log_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    daily_log_id INTEGER NOT NULL REFERENCES daily_logs(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    scheduled_at TEXT NOT NULL,     -- ISO datetime airtime
    event_type TEXT NOT NULL,
    track_id INTEGER REFERENCES tracks(id),
    title TEXT,
    artist TEXT,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    timing_mode TEXT NOT NULL DEFAULT 'FLOAT',
    chain_mode TEXT NOT NULL DEFAULT 'AUTO',
    status TEXT NOT NULL DEFAULT 'DRAFT',
    manual_flag TEXT NOT NULL DEFAULT 'AUTO',
    category_code TEXT,
    clock_slot_id INTEGER REFERENCES clock_slots(id),
    score REAL,
    notes TEXT,
    UNIQUE(daily_log_id, position)
);

CREATE INDEX IF NOT EXISTS idx_log_events_scheduled ON log_events(scheduled_at);
CREATE INDEX IF NOT EXISTS idx_log_events_status ON log_events(status);

-- As-played history
CREATE TABLE IF NOT EXISTS as_played (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    log_event_id INTEGER REFERENCES log_events(id),
    track_id INTEGER REFERENCES tracks(id),
    played_at TEXT NOT NULL,
    scheduled_at TEXT,
    event_type TEXT,
    title TEXT,
    artist TEXT,
    duration_ms INTEGER,
    outcome TEXT NOT NULL DEFAULT 'PLAYED',  -- PLAYED / SKIPPED / FAILED / STOPPED
    engine TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_as_played_played_at ON as_played(played_at);

-- Daypart → clock assignments (simple M1 grid)
CREATE TABLE IF NOT EXISTS daypart_clocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hour INTEGER NOT NULL CHECK(hour >= 0 AND hour <= 23),
    clock_id INTEGER NOT NULL REFERENCES clocks(id),
    day_mask INTEGER NOT NULL DEFAULT 127,  -- bitmask Sun=1 .. Sat=64, default all
    UNIQUE(hour, day_mask)
);
