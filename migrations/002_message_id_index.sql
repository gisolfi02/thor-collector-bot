CREATE INDEX IF NOT EXISTS idx_spawns_message
ON spawns(guild_id, channel_id, message_id);
