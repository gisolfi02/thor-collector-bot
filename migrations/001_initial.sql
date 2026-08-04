CREATE TABLE IF NOT EXISTS guild_configs (
    guild_id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL,
    game_admin_user_id INTEGER NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    min_spawn_minutes INTEGER NOT NULL CHECK (min_spawn_minutes BETWEEN 1 AND 10080),
    max_spawn_minutes INTEGER NOT NULL CHECK (max_spawn_minutes BETWEEN 1 AND 10080),
    last_collectible_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (min_spawn_minutes <= max_spawn_minutes)
);

CREATE TABLE IF NOT EXISTS collectibles (
    collectible_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    filename TEXT NOT NULL,
    caption TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    rarity TEXT NOT NULL,
    is_enabled INTEGER NOT NULL DEFAULT 1 CHECK (is_enabled IN (0, 1))
);

CREATE TABLE IF NOT EXISTS spawns (
    spawn_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    collectible_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'CAPTURED', 'CANCELLED', 'INVALIDATED')),
    spawned_at TEXT NOT NULL,
    captured_at TEXT,
    captured_by_user_id INTEGER,
    FOREIGN KEY (guild_id) REFERENCES guild_configs(guild_id) ON DELETE CASCADE,
    FOREIGN KEY (collectible_id) REFERENCES collectibles(collectible_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_spawn_per_guild
ON spawns(guild_id) WHERE status = 'ACTIVE';

CREATE INDEX IF NOT EXISTS idx_spawns_guild_status
ON spawns(guild_id, status);

CREATE TABLE IF NOT EXISTS user_collections (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    collectible_id TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    first_captured_at TEXT NOT NULL,
    last_captured_at TEXT NOT NULL,
    PRIMARY KEY (guild_id, user_id, collectible_id),
    FOREIGN KEY (guild_id) REFERENCES guild_configs(guild_id) ON DELETE CASCADE,
    FOREIGN KEY (collectible_id) REFERENCES collectibles(collectible_id)
);

CREATE TABLE IF NOT EXISTS captures (
    capture_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    collectible_id TEXT NOT NULL,
    spawn_id INTEGER NOT NULL UNIQUE,
    captured_at TEXT NOT NULL,
    capture_time_ms INTEGER NOT NULL CHECK (capture_time_ms >= 0),
    FOREIGN KEY (guild_id) REFERENCES guild_configs(guild_id) ON DELETE CASCADE,
    FOREIGN KEY (collectible_id) REFERENCES collectibles(collectible_id),
    FOREIGN KEY (spawn_id) REFERENCES spawns(spawn_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_captures_leaderboard
ON captures(guild_id, user_id, captured_at);

CREATE INDEX IF NOT EXISTS idx_collections_lookup
ON user_collections(guild_id, user_id, collectible_id);
