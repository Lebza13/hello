"""SQLite storage. One file (data/mtd.db) keeps every day ever uploaded."""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from . import fields as F

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    report TEXT NOT NULL,
    date   TEXT NOT NULL,          -- ISO yyyy-mm-dd
    field  TEXT NOT NULL,
    value  REAL,
    PRIMARY KEY (report, date, field)
);
CREATE TABLE IF NOT EXISTS days (
    report      TEXT NOT NULL,
    date        TEXT NOT NULL,
    source_file TEXT,
    note        TEXT,
    updated_at  TEXT,
    PRIMARY KEY (report, date)
);
CREATE TABLE IF NOT EXISTS uploads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    uploaded_at TEXT,
    filename    TEXT,
    stored_as   TEXT,
    summary     TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    scope TEXT NOT NULL,           -- 'yyyy-mm' for month settings, 'global' otherwise
    key   TEXT NOT NULL,
    value REAL,
    PRIMARY KEY (scope, key)
);
CREATE TABLE IF NOT EXISTS calendar (
    date   TEXT PRIMARY KEY,
    shifts REAL,
    status TEXT,
    note   TEXT
);
CREATE TABLE IF NOT EXISTS actions (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    status   TEXT,
    finding  TEXT,
    action   TEXT,
    owner    TEXT,
    due      TEXT,
    measure  TEXT,
    closed   INTEGER DEFAULT 0,
    created  TEXT
);
"""


class DB:
    def __init__(self, path):
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._mem = sqlite3.connect(path, check_same_thread=False) if path == ":memory:" else None
        with self.conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def conn(self):
        c = self._mem or sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            if not self._mem:
                c.close()

    # ---- daily report values -------------------------------------------------
    def save_day(self, report, date, values, source_file=None, note=None, replace=True):
        """Store one report for one date. Blank (None) values are stored as NULL,
        meaning 'not reported' - never assumed to be zero."""
        now = datetime.now().isoformat(timespec="seconds")
        with self.conn() as c:
            if replace:
                c.execute("DELETE FROM entries WHERE report=? AND date=?", (report, date))
            for k, v in values.items():
                c.execute("INSERT OR REPLACE INTO entries(report,date,field,value) VALUES(?,?,?,?)",
                          (report, date, k, v))
            c.execute("""INSERT INTO days(report,date,source_file,note,updated_at) VALUES(?,?,?,?,?)
                         ON CONFLICT(report,date) DO UPDATE SET
                           source_file=COALESCE(excluded.source_file, days.source_file),
                           note=COALESCE(excluded.note, days.note), updated_at=excluded.updated_at""",
                      (report, date, source_file, note, now))

    def delete_day(self, report, date):
        with self.conn() as c:
            c.execute("DELETE FROM entries WHERE report=? AND date=?", (report, date))
            c.execute("DELETE FROM days WHERE report=? AND date=?", (report, date))

    def days(self, report, month=None):
        """Return [{date, note, source_file, values{field: value}}] ordered by date."""
        q = "SELECT * FROM days WHERE report=?"
        args = [report]
        if month:
            q += " AND substr(date,1,7)=?"
            args.append(month)
        q += " ORDER BY date"
        with self.conn() as c:
            rows = [dict(r) for r in c.execute(q, args)]
            for r in rows:
                r["values"] = {e["field"]: e["value"] for e in c.execute(
                    "SELECT field,value FROM entries WHERE report=? AND date=?", (report, r["date"]))}
        return rows

    def day(self, report, date):
        with self.conn() as c:
            d = c.execute("SELECT * FROM days WHERE report=? AND date=?", (report, date)).fetchone()
            if not d:
                return None
            d = dict(d)
            d["values"] = {e["field"]: e["value"] for e in c.execute(
                "SELECT field,value FROM entries WHERE report=? AND date=?", (report, date))}
            return d

    def months(self):
        with self.conn() as c:
            return [r[0] for r in c.execute(
                "SELECT DISTINCT substr(date,1,7) m FROM days ORDER BY m DESC")]

    # ---- uploads log ----------------------------------------------------------
    def log_upload(self, filename, stored_as, summary):
        with self.conn() as c:
            c.execute("INSERT INTO uploads(uploaded_at,filename,stored_as,summary) VALUES(?,?,?,?)",
                      (datetime.now().isoformat(timespec="seconds"), filename, stored_as, summary))

    def uploads(self, limit=50):
        with self.conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM uploads ORDER BY id DESC LIMIT ?", (limit,))]

    # ---- settings ---------------------------------------------------------------
    def settings(self, scope, defs):
        with self.conn() as c:
            stored = {r["key"]: r["value"] for r in c.execute("SELECT key,value FROM settings WHERE scope=?", (scope,))}
        return {d["key"]: stored.get(d["key"], d["default"]) for d in defs}

    def month_settings(self, month):
        return self.settings(month, F.SETTINGS)

    def spillage_settings(self):
        return self.settings("global", F.SPILLAGE_SETTINGS)

    def set_setting(self, scope, key, value):
        with self.conn() as c:
            c.execute("INSERT OR REPLACE INTO settings(scope,key,value) VALUES(?,?,?)", (scope, key, value))

    # ---- calendar -----------------------------------------------------------------
    def calendar_overrides(self, month):
        with self.conn() as c:
            return {r["date"]: dict(r) for r in c.execute(
                "SELECT * FROM calendar WHERE substr(date,1,7)=?", (month,))}

    def set_calendar(self, date, shifts, status, note):
        with self.conn() as c:
            c.execute("INSERT OR REPLACE INTO calendar(date,shifts,status,note) VALUES(?,?,?,?)",
                      (date, shifts, status, note))

    def clear_calendar(self, date):
        with self.conn() as c:
            c.execute("DELETE FROM calendar WHERE date=?", (date,))

    # ---- actions --------------------------------------------------------------------
    def actions(self, include_closed=False):
        q = "SELECT * FROM actions" + ("" if include_closed else " WHERE closed=0") + " ORDER BY closed, id"
        with self.conn() as c:
            return [dict(r) for r in c.execute(q)]

    def save_action(self, a, action_id=None):
        cols = ["status", "finding", "action", "owner", "due", "measure", "closed"]
        vals = [a.get(k) for k in cols]
        with self.conn() as c:
            if action_id:
                c.execute(f"UPDATE actions SET {','.join(k + '=?' for k in cols)} WHERE id=?", vals + [action_id])
            else:
                c.execute(f"INSERT INTO actions({','.join(cols)},created) VALUES({','.join('?' * len(cols))},?)",
                          vals + [datetime.now().isoformat(timespec='seconds')])

    def delete_action(self, action_id):
        with self.conn() as c:
            c.execute("DELETE FROM actions WHERE id=?", (action_id,))
