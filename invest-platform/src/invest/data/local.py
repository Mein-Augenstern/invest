"""本地存储：SQLite。

- series(instrument, kind, date, close, source)：统一时序表，幂等 upsert，带数据血缘
- csi_catalog(index_code, name, full_name)：中证指数目录缓存（名称→代码解析用）
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS series (
    instrument TEXT NOT NULL,
    kind TEXT NOT NULL,
    date TEXT NOT NULL,
    close REAL,
    source TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (instrument, kind, date)
);
CREATE TABLE IF NOT EXISTS csi_catalog (
    index_code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    full_name TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fund_holdings (
    instrument TEXT NOT NULL,
    period TEXT NOT NULL,
    rank INTEGER NOT NULL,
    stock_code TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    weight REAL NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (instrument, period, rank)
);
CREATE TABLE IF NOT EXISTS fund_industry (
    instrument TEXT NOT NULL,
    report_date TEXT NOT NULL,
    industry TEXT NOT NULL,
    weight REAL NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (instrument, report_date, industry)
);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    rule_ref TEXT NOT NULL,
    metric TEXT NOT NULL,
    metric_value TEXT NOT NULL,
    action TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT '建议',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS diary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL,
    mood TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS instruments (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    code TEXT NOT NULL DEFAULT '',
    benchmark_index TEXT NOT NULL DEFAULT '',
    benchmark_tr_code TEXT NOT NULL DEFAULT '',
    account TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
"""


class LocalStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def upsert_series(self, instrument: str, kind: str, df: pd.DataFrame, source: str = "") -> int:
        now = datetime.now().isoformat(timespec="seconds")
        rows = [(instrument, kind, r.date, float(r.close), source, now) for r in df.itertuples()]
        with self._conn() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO series VALUES (?,?,?,?,?,?)", rows
            )
        return len(rows)

    def read_series(self, instrument: str, kind: str) -> pd.DataFrame:
        sql = (
            "SELECT date, close FROM series WHERE instrument=? AND kind=? ORDER BY date"
        )
        with self._conn() as conn:
            return pd.read_sql_query(sql, conn, params=(instrument, kind))

    def latest(self, instrument: str, kind: str) -> tuple[str, float] | None:
        sql = (
            "SELECT date, close FROM series WHERE instrument=? AND kind=? "
            "ORDER BY date DESC LIMIT 1"
        )
        with self._conn() as conn:
            row = conn.execute(sql, (instrument, kind)).fetchone()
        return (row[0], row[1]) if row else None

    # ---- 中证指数目录 ----

    def upsert_catalog(self, code_name: pd.DataFrame) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        rows = [
            (r.index_code, r.name, r.full_name, now) for r in code_name.itertuples()
        ]
        with self._conn() as conn:
            conn.executemany("INSERT OR REPLACE INTO csi_catalog VALUES (?,?,?,?)", rows)
        return len(rows)

    # ---- 信号留痕 ----

    def add_signals(self, signals: list) -> list[int]:
        """落库（同日同标的同规则同动作去重），返回新增行的 id 列表。"""
        now = datetime.now().isoformat(timespec="seconds")
        new_ids: list[int] = []
        with self._conn() as conn:
            for s in signals:
                dup = conn.execute(
                    "SELECT id FROM signals WHERE date=? AND instrument_id=? AND rule_ref=? AND action=?",
                    (s.date, s.instrument_id, s.rule_ref, s.action),
                ).fetchone()
                if dup:
                    continue
                cur = conn.execute(
                    "INSERT INTO signals(date, instrument_id, rule_ref, metric, metric_value, action, status, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (s.date, s.instrument_id, s.rule_ref, s.metric, s.metric_value, s.action, s.status, now),
                )
                new_ids.append(cur.lastrowid)
        return new_ids

    def recent_signals(self, limit: int = 10, status: str | None = None) -> list[tuple]:
        """最近信号；status 传入则只取该状态（如总览页只显示活跃的'建议'）。"""
        sql = (
            "SELECT id, date, instrument_id, rule_ref, metric, metric_value, action, status"
            " FROM signals"
        )
        params: tuple = ()
        if status:
            sql += " WHERE status = ?"
            params = (status,)
        sql += " ORDER BY id DESC LIMIT ?"
        with self._conn() as conn:
            return conn.execute(sql, params + (limit,)).fetchall()

    def update_signal_status(self, signal_id: int, status: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE signals SET status=? WHERE id=?", (status, signal_id)
            )
            return cur.rowcount > 0

    # ---- 投资日记（R5，有知有行式复盘） ----

    def upsert_diary(self, date: str, content: str, mood: str = "") -> bool:
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO diary(date, content, mood, created_at, updated_at) VALUES (?,?,?,?,?)"
                " ON CONFLICT(date) DO UPDATE SET content=excluded.content, mood=excluded.mood, updated_at=excluded.updated_at",
                (date, content, mood, now, now),
            )
            return cur.rowcount > 0

    def delete_diary(self, date: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM diary WHERE date=?", (date,))
            return cur.rowcount > 0

    def list_diary(self, limit: int = 50) -> list[tuple]:
        with self._conn() as conn:
            return conn.execute(
                "SELECT date, content, mood, updated_at FROM diary ORDER BY date DESC LIMIT ?", (limit,)
            ).fetchall()

    def get_diary(self, date: str) -> tuple | None:
        with self._conn() as conn:
            return conn.execute(
                "SELECT date, content, mood, updated_at FROM diary WHERE date=?", (date,)
            ).fetchone()

    # ---- 标的管理（S2：小程序端 CRUD，yaml 仅作种子） ----

    def upsert_instrument(self, row: dict) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO instruments(id, type, name, code, benchmark_index, benchmark_tr_code, account, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET type=excluded.type, name=excluded.name, code=excluded.code,"
                " benchmark_index=excluded.benchmark_index, benchmark_tr_code=excluded.benchmark_tr_code,"
                " account=excluded.account, updated_at=excluded.updated_at",
                (row["id"], row["type"], row["name"], row.get("code", ""),
                 row.get("benchmark_index", ""), row.get("benchmark_tr_code", ""),
                 row.get("account", ""), now),
            )

    def delete_instrument(self, ins_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM instruments WHERE id=?", (ins_id,))
            return cur.rowcount > 0

    def list_instruments(self) -> list[tuple]:
        with self._conn() as conn:
            return conn.execute(
                "SELECT id, type, name, code, benchmark_index, benchmark_tr_code, account FROM instruments ORDER BY id"
            ).fetchall()

    # ---- 中证指数目录 ----

    def resolve_index_code(self, name: str) -> str | None:
        """精确简称 > 全称包含 > 简称包含，取第一个命中。"""
        fuzzy = f"%{name}%"
        with self._conn() as conn:
            for sql, param in (
                ("SELECT index_code FROM csi_catalog WHERE name = ? LIMIT 1", name),
                ("SELECT index_code FROM csi_catalog WHERE full_name LIKE ? LIMIT 1", fuzzy),
                ("SELECT index_code FROM csi_catalog WHERE name LIKE ? LIMIT 1", fuzzy),
            ):
                row = conn.execute(sql, (param,)).fetchone()
                if row:
                    return row[0]
        return None

    # ---- 基金透视（持仓穿透，数据源：基金定期报告） ----

    def upsert_fund_holdings(self, instrument: str, period: str, rows: list[tuple]) -> int:
        """rows: [(rank, stock_code, stock_name, weight比例)]"""
        now = datetime.now().isoformat(timespec="seconds")
        data = [(instrument, period, r[0], r[1], r[2], float(r[3]), now) for r in rows]
        with self._conn() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO fund_holdings VALUES (?,?,?,?,?,?,?)", data
            )
        return len(data)

    def fund_holdings(self, instrument: str, period: str | None = None) -> list[tuple]:
        sql = "SELECT rank, stock_code, stock_name, weight FROM fund_holdings WHERE instrument=?"
        params: list = [instrument]
        if period:
            sql += " AND period=?"
            params.append(period)
        else:
            sql += " AND period=(SELECT MAX(period) FROM fund_holdings WHERE instrument=?)"
            params.append(instrument)
        sql += " ORDER BY rank"
        with self._conn() as conn:
            return conn.execute(sql, params).fetchall()

    def fund_holdings_period(self, instrument: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT MAX(period) FROM fund_holdings WHERE instrument=?", (instrument,)
            ).fetchone()
        return row[0] if row else None

    def upsert_fund_industry(self, instrument: str, report_date: str, rows: list[tuple]) -> int:
        """rows: [(industry, weight比例)]"""
        now = datetime.now().isoformat(timespec="seconds")
        data = [(instrument, report_date, i[0], float(i[1]), now) for i in rows]
        with self._conn() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO fund_industry VALUES (?,?,?,?,?)", data
            )
        return len(data)

    def fund_industry(self, instrument: str) -> list[tuple]:
        sql = (
            "SELECT industry, weight FROM fund_industry WHERE instrument=? "
            "AND report_date=(SELECT MAX(report_date) FROM fund_industry WHERE instrument=?) "
            "ORDER BY weight DESC"
        )
        with self._conn() as conn:
            return conn.execute(sql, (instrument, instrument)).fetchall()
