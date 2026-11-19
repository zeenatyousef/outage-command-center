"""SQLite storage. One shared connection guarded by a re-entrant lock."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  type TEXT NOT NULL,              -- core | hub | tower | cabinet
  parent_id TEXT,
  backup_parent_id TEXT,           -- alternative uplink (failover path)
  lat REAL, lng REAL,
  area TEXT,
  status TEXT NOT NULL DEFAULT 'up' -- up | degraded | down (derived, cached here)
);

CREATE TABLE IF NOT EXISTS customers (
  id INTEGER PRIMARY KEY,
  name TEXT,
  area TEXT,
  node_id TEXT NOT NULL,
  plan TEXT,
  priority TEXT NOT NULL DEFAULT 'home'  -- home | business | enterprise
);
CREATE INDEX IF NOT EXISTS idx_customers_node ON customers(node_id);

CREATE TABLE IF NOT EXISTS incidents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  root_node_id TEXT NOT NULL,
  title TEXT,
  kind TEXT NOT NULL DEFAULT 'outage',        -- outage | degradation | flapping
  inferred INTEGER NOT NULL DEFAULT 0,        -- 1 = root cause inferred from child alerts
  status TEXT NOT NULL DEFAULT 'investigating', -- investigating | mitigated | resolved
  severity TEXT NOT NULL DEFAULT 'minor',     -- minor | major | critical (from peak score)
  severity_score REAL NOT NULL DEFAULT 0,     -- current weighted impact
  peak_score REAL NOT NULL DEFAULT 0,
  started_ts REAL NOT NULL,
  last_alert_ts REAL NOT NULL,
  mitigated_ts REAL,
  resolved_ts REAL,
  customers_offline INTEGER NOT NULL DEFAULT 0,
  customers_degraded INTEGER NOT NULL DEFAULT 0,
  business_affected INTEGER NOT NULL DEFAULT 0,
  peak_offline INTEGER NOT NULL DEFAULT 0,
  peak_degraded INTEGER NOT NULL DEFAULT 0,
  raw_alert_count INTEGER NOT NULL DEFAULT 0,
  flap_count INTEGER NOT NULL DEFAULT 0,
  notified_level TEXT NOT NULL DEFAULT '',
  areas TEXT NOT NULL DEFAULT '',
  status_update TEXT,
  status_update_source TEXT,                  -- template | ai | edited
  technical_summary TEXT,
  merged_into INTEGER
);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);

CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT UNIQUE,
  node_id TEXT NOT NULL,
  type TEXT NOT NULL,
  severity TEXT,
  message TEXT,
  ts REAL NOT NULL,
  last_ts REAL NOT NULL,
  count INTEGER NOT NULL DEFAULT 1,           -- how many raw alerts collapsed into this row
  state TEXT NOT NULL DEFAULT 'open',         -- open | cleared
  cleared_ts REAL,
  incident_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_alerts_state ON alerts(state);
CREATE INDEX IF NOT EXISTS idx_alerts_node ON alerts(node_id, type, state);
CREATE INDEX IF NOT EXISTS idx_alerts_incident ON alerts(incident_id);

CREATE TABLE IF NOT EXISTS incident_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  incident_id INTEGER NOT NULL,
  ts REAL NOT NULL,
  message TEXT NOT NULL,
  author TEXT NOT NULL DEFAULT 'system'
);
CREATE INDEX IF NOT EXISTS idx_events_incident ON incident_events(incident_id);

CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  incident_id INTEGER,
  level TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT,
  is_read INTEGER NOT NULL DEFAULT 0
);
"""


class Database:
    def __init__(self, path: str = ":memory:"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self._depth = 0
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.executescript(SCHEMA)

    @contextmanager
    def transaction(self):
        with self.lock:
            if self._depth == 0:
                self.conn.execute("BEGIN")
            self._depth += 1
            try:
                yield
            except BaseException:
                self._depth -= 1
                if self._depth == 0:
                    self.conn.execute("ROLLBACK")
                raise
            else:
                self._depth -= 1
                if self._depth == 0:
                    self.conn.execute("COMMIT")

    def execute(self, sql: str, params=()):
        with self.lock:
            return self.conn.execute(sql, params)

    def executemany(self, sql: str, rows):
        with self.lock:
            return self.conn.executemany(sql, rows)

    def query(self, sql: str, params=()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params=()) -> dict | None:
        with self.lock:
            r = self.conn.execute(sql, params).fetchone()
            return dict(r) if r else None

    def scalar(self, sql: str, params=(), default=None):
        with self.lock:
            r = self.conn.execute(sql, params).fetchone()
            return r[0] if r and r[0] is not None else default
