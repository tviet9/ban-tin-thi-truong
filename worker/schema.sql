-- Chạy lại nhiều lần không sao (IF NOT EXISTS)
CREATE TABLE IF NOT EXISTS sources (kind TEXT NOT NULL, value TEXT NOT NULL, title TEXT, created_at TEXT, PRIMARY KEY (kind, value));
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS hours (hour TEXT PRIMARY KEY, day TEXT, data TEXT);
CREATE INDEX IF NOT EXISTS hours_day ON hours(day);
CREATE TABLE IF NOT EXISTS digests (day TEXT PRIMARY KEY, data TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS messages (uid TEXT PRIMARY KEY, day TEXT, date TEXT, data TEXT);
CREATE INDEX IF NOT EXISTS messages_day ON messages(day);
CREATE TABLE IF NOT EXISTS watch (uid TEXT PRIMARY KEY, day TEXT, date TEXT, data TEXT);
CREATE INDEX IF NOT EXISTS watch_day ON watch(day);
CREATE TABLE IF NOT EXISTS links (url TEXT NOT NULL, day TEXT NOT NULL, date TEXT, data TEXT, PRIMARY KEY (url, day));
CREATE TABLE IF NOT EXISTS tokens (address TEXT PRIMARY KEY, first_price REAL, first_at TEXT, first_mention TEXT, symbol TEXT);
CREATE TABLE IF NOT EXISTS token_days (day TEXT NOT NULL, address TEXT NOT NULL, data TEXT, PRIMARY KEY (day, address));
CREATE TABLE IF NOT EXISTS stats (day TEXT PRIMARY KEY, data TEXT);
CREATE TABLE IF NOT EXISTS x_posts (uid TEXT PRIMARY KEY, day TEXT, date TEXT, data TEXT);
CREATE INDEX IF NOT EXISTS x_posts_day ON x_posts(day);
CREATE TABLE IF NOT EXISTS x_trend (day TEXT PRIMARY KEY, data TEXT);
