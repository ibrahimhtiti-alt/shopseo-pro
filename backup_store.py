# -*- coding: utf-8 -*-
"""SQLite-backed backup and rollback system for Shopify write operations."""

import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

from models import BackupEntry


class BackupStore:
    """Stores before/after snapshots of every Shopify write for safe rollback."""

    def __init__(self, db_path: str = "backups.db"):
        # Docker: use /app/data/ if it exists, otherwise project root
        data_dir = Path(__file__).resolve().parent / "data"
        if data_dir.is_dir():
            self.db_path = data_dir / db_path
        else:
            self.db_path = Path(__file__).resolve().parent / db_path
        self._init_db()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Create the backups table if it does not exist yet."""
        with sqlite3.connect(str(self.db_path)) as conn:
            # WAL mode for better concurrent read/write safety
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS backups (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    resource_type TEXT    NOT NULL,
                    resource_id   INTEGER NOT NULL,
                    timestamp     TEXT    NOT NULL,
                    before_json   TEXT    NOT NULL,
                    after_json    TEXT    DEFAULT '',
                    rolled_back   INTEGER DEFAULT 0
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_backups_resource_id ON backups(resource_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_backups_timestamp ON backups(timestamp)"
            )
            conn.commit()

    def _row_to_entry(self, row: tuple) -> BackupEntry:
        """Convert a raw database row into a *BackupEntry* model."""
        return BackupEntry(
            id=row[0],
            resource_type=row[1],
            resource_id=row[2],
            timestamp=row[3],
            before_state=json.loads(row[4]) if row[4] else {},
            after_state=json.loads(row[5]) if row[5] else {},
            rolled_back=bool(row[6]),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_backup(
        self, resource_type: str, resource_id: int, before_state: dict
    ) -> int:
        """Persist a *before* snapshot and return the new backup id."""
        ts = datetime.now(timezone.utc).isoformat()
        before_json = json.dumps(before_state, ensure_ascii=False)
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.execute(
                """
                INSERT INTO backups (resource_type, resource_id, timestamp, before_json)
                VALUES (?, ?, ?, ?)
                """,
                (resource_type, resource_id, ts, before_json),
            )
            conn.commit()
            return cursor.lastrowid  # type: ignore[return-value]

    def update_after_state(self, backup_id: int, after_state: dict) -> None:
        """Attach the *after* snapshot once the Shopify write succeeds."""
        after_json = json.dumps(after_state, ensure_ascii=False)
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "UPDATE backups SET after_json = ? WHERE id = ?",
                (after_json, backup_id),
            )
            conn.commit()

    def get_backup(self, backup_id: int) -> BackupEntry | None:
        """Fetch a single backup by its id, or *None* if not found."""
        with sqlite3.connect(str(self.db_path)) as conn:
            row = conn.execute(
                "SELECT * FROM backups WHERE id = ?", (backup_id,)
            ).fetchone()
            if row is None:
                return None
            return self._row_to_entry(row)

    def list_backups(
        self, resource_id: int | None = None, limit: int = 50
    ) -> list[BackupEntry]:
        """Return the most recent backups, optionally filtered by resource."""
        with sqlite3.connect(str(self.db_path)) as conn:
            if resource_id is not None:
                rows = conn.execute(
                    "SELECT * FROM backups WHERE resource_id = ? ORDER BY id DESC LIMIT ?",
                    (resource_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM backups ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [self._row_to_entry(r) for r in rows]

    def mark_rolled_back(self, backup_id: int) -> None:
        """Flag a backup as having been rolled back."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "UPDATE backups SET rolled_back = 1 WHERE id = ?",
                (backup_id,),
            )
            conn.commit()

    def cleanup_old_backups(self, max_age_days: int = 90) -> int:
        """Delete backups older than *max_age_days*. Returns count of deleted rows."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=max_age_days)
        ).isoformat()
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.execute(
                "DELETE FROM backups WHERE timestamp < ?", (cutoff,)
            )
            conn.commit()
            return cursor.rowcount

    def get_last_optimization(self, resource_id: int) -> str | None:
        """Return the ISO timestamp of the most recent (non-rolled-back) optimization for a resource."""
        with sqlite3.connect(str(self.db_path)) as conn:
            row = conn.execute(
                "SELECT timestamp FROM backups "
                "WHERE resource_id = ? AND rolled_back = 0 AND after_json != '' "
                "ORDER BY id DESC LIMIT 1",
                (resource_id,),
            ).fetchone()
            return row[0] if row else None

    def get_optimized_resource_ids(self, since_days: int = 7) -> dict[int, str]:
        """Return a dict of {resource_id: timestamp} for all resources optimized within *since_days*."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=since_days)
        ).isoformat()
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute(
                "SELECT resource_id, MAX(timestamp) FROM backups "
                "WHERE rolled_back = 0 AND after_json != '' AND timestamp >= ? "
                "GROUP BY resource_id",
                (cutoff,),
            ).fetchall()
            return {row[0]: row[1] for row in rows}

    def get_restore_data(self, backup_id: int) -> dict | None:
        """Return the *before* state dict for restoring a resource."""
        with sqlite3.connect(str(self.db_path)) as conn:
            row = conn.execute(
                "SELECT before_json FROM backups WHERE id = ?", (backup_id,)
            ).fetchone()
            if row is None or not row[0]:
                return None
            return json.loads(row[0])

    # ------------------------------------------------------------------
    # Dashboard / Statistics helpers
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        """Return statistics for the dashboard.

        Returns dict with keys:
            total_backups, total_optimized_7d, total_optimized_30d,
            recent_backups (list of last 10 BackupEntry).
        """
        with sqlite3.connect(str(self.db_path)) as conn:
            total = conn.execute("SELECT COUNT(*) FROM backups").fetchone()[0]

            cutoff_7 = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
            opt_7 = conn.execute(
                "SELECT COUNT(DISTINCT resource_id) FROM backups "
                "WHERE rolled_back = 0 AND after_json != '' AND timestamp >= ?",
                (cutoff_7,),
            ).fetchone()[0]

            cutoff_30 = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            opt_30 = conn.execute(
                "SELECT COUNT(DISTINCT resource_id) FROM backups "
                "WHERE rolled_back = 0 AND after_json != '' AND timestamp >= ?",
                (cutoff_30,),
            ).fetchone()[0]

            recent_rows = conn.execute(
                "SELECT * FROM backups ORDER BY id DESC LIMIT 10"
            ).fetchall()

        return {
            "total_backups": total,
            "total_optimized_7d": opt_7,
            "total_optimized_30d": opt_30,
            "recent_backups": [self._row_to_entry(r) for r in recent_rows],
        }

    def get_daily_optimization_counts(self, days: int = 30) -> list[dict]:
        """Return daily optimization counts for the last *days* days.

        Returns list of dicts: {date: 'YYYY-MM-DD', count: int}.
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat()
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute(
                """
                SELECT DATE(timestamp) AS day, COUNT(*) AS cnt
                FROM backups
                WHERE rolled_back = 0 AND after_json != '' AND timestamp >= ?
                GROUP BY day
                ORDER BY day ASC
                """,
                (cutoff,),
            ).fetchall()
        return [{"date": row[0], "count": row[1]} for row in rows]

    def list_backup_groups(self, limit: int = 20) -> list[dict]:
        """Group backups by minute-level timestamp for batch rollback.

        Returns list of dicts: {minute, count, backup_ids, titles, resource_type}.
        """
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute(
                """
                SELECT
                    SUBSTR(timestamp, 1, 16) AS minute,
                    GROUP_CONCAT(id) AS ids,
                    GROUP_CONCAT(resource_id) AS resource_ids,
                    COUNT(*) AS cnt,
                    resource_type,
                    MIN(rolled_back) AS any_active
                FROM backups
                WHERE after_json != ''
                GROUP BY minute, resource_type
                HAVING cnt > 1
                ORDER BY minute DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        groups = []
        for row in rows:
            groups.append({
                "minute": row[0],
                "backup_ids": [int(x) for x in row[1].split(",")],
                "resource_ids": [int(x) for x in row[2].split(",")],
                "count": row[3],
                "resource_type": row[4],
                "has_active": row[5] == 0,  # at least one not rolled back
            })
        return groups
