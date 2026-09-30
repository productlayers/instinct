"""What NPCs have learned about each player, stored in SQLite.

Lessons are keyed by player, not by NPC. When one guard learns something about a
player, every other NPC deciding about that player sees it on its next decision.
Point it at a file and the lessons survive restarts; the default ":memory:" does not.
"""
import sqlite3
import threading
import time


class LessonStore:
    def __init__(self, path: str = ":memory:"):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        with self._lock, self._db:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS lessons ("
                " player TEXT NOT NULL,"
                " lesson TEXT NOT NULL,"
                " created_at REAL NOT NULL,"
                " PRIMARY KEY (player, lesson))"
            )

    def add(self, player: str, lesson: str) -> bool:
        """Record a lesson. Returns False if this player already had it."""
        with self._lock, self._db:
            cur = self._db.execute(
                "INSERT OR IGNORE INTO lessons (player, lesson, created_at) VALUES (?, ?, ?)",
                (player, lesson, time.time()),
            )
        return cur.rowcount == 1

    def get(self, player: str) -> list[str]:
        with self._lock:
            rows = self._db.execute(
                "SELECT lesson FROM lessons WHERE player = ? ORDER BY created_at, rowid",
                (player,),
            ).fetchall()
        return [r[0] for r in rows]

    def forget(self, player: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM lessons WHERE player = ?", (player,))

    def close(self) -> None:
        with self._lock:
            self._db.close()
