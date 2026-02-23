import sqlite3
from pathlib import Path
from typing import Optional


class SeenStore:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_tweets (
                tweet_id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                source TEXT NOT NULL,
                first_seen_at TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    def is_seen(self, tweet_id: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM seen_tweets WHERE tweet_id = ?", (tweet_id,))
        return cur.fetchone() is not None

    def mark_seen(self, tweet_id: str, url: str, source: str, first_seen_at: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO seen_tweets (tweet_id, url, source, first_seen_at) VALUES (?, ?, ?, ?)",
            (tweet_id, url, source, first_seen_at),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
