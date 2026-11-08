"""本地存储：SQLite。

- series(instrument, kind, date, close, source)：统一时序表，幂等 upsert，带数据血缘
- csi_catalog(index_code, name, full_name)：中证指数目录缓存（名称→代码解析用）
- S11 会员隔离：trades/audit_log 新表；signals/diary/instruments 增加 member_id 维度；
  member_id=None 的调用回落默认会员（兼容单用户时代的 CLI/测试/调度器语义）
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd


def default_member_id() -> int:
    """默认会员（token/本机模式、CLI 与调度器等无登录态场景）。

    生产通过 INVEST_DEFAULT_MEMBER_ID 指向运营者 member（ECS=31）；
    历史 NULL 行迁移时也归并到该会员。
    """
    try:
        return int(os.environ.get("INVEST_DEFAULT_MEMBER_ID", "1"))
    except ValueError:
        return 1


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
CREATE INDEX IF NOT EXISTS idx_csi_catalog_name ON csi_catalog(name);
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
    member_id INTEGER NOT NULL DEFAULT 1,
    date TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    rule_ref TEXT NOT NULL,
    metric TEXT NOT NULL,
    metric_value TEXT NOT NULL,
    action TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT '建议',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signals_dedup ON signals(date, instrument_id, rule_ref, action);
CREATE INDEX IF NOT EXISTS idx_signals_status_id ON signals(status, id);
CREATE TABLE IF NOT EXISTS diary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL DEFAULT 1,
    date TEXT NOT NULL,
    content TEXT NOT NULL,
    mood TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (member_id, date)
);
CREATE TABLE IF NOT EXISTS instruments (
    member_id INTEGER NOT NULL DEFAULT 1,
    id TEXT NOT NULL,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    code TEXT NOT NULL DEFAULT '',
    benchmark_index TEXT NOT NULL DEFAULT '',
    benchmark_tr_code TEXT NOT NULL DEFAULT '',
    account TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (member_id, id)
);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    action TEXT NOT NULL,
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    fee REAL NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trades_member_date ON trades(member_id, date);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    trace_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_member ON audit_log(member_id, id);
"""


def _migrate_member_columns(conn: sqlite3.Connection) -> None:
    """旧库升级（S11）：signals/instruments 补 member_id 列；diary/instruments
    重建为复合唯一/复合主键；历史 NULL 行归并到默认会员。幂等可重跑。"""
    default = default_member_id()

    if "member_id" not in {r[1] for r in conn.execute("PRAGMA table_info(signals)").fetchall()}:
        conn.execute("ALTER TABLE signals ADD COLUMN member_id INTEGER")
        conn.execute("UPDATE signals SET member_id=? WHERE member_id IS NULL", (default,))
    conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_member ON signals(member_id, id)")

    # diary：UNIQUE(date) → UNIQUE(member_id, date)（SQLite 无法改约束，重建小表）
    dcols = {r[1] for r in conn.execute("PRAGMA table_info(diary)").fetchall()}
    if "member_id" not in dcols:
        conn.execute("ALTER TABLE diary RENAME TO diary_old")
        conn.executescript(
            "CREATE TABLE diary (id INTEGER PRIMARY KEY AUTOINCREMENT, member_id INTEGER NOT NULL DEFAULT 1,"
            " date TEXT NOT NULL, content TEXT NOT NULL, mood TEXT NOT NULL DEFAULT '',"
            " created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE (member_id, date));"
        )
        conn.execute(
            "INSERT INTO diary(member_id, date, content, mood, created_at, updated_at)"
            " SELECT ?, date, IFNULL(content,''), IFNULL(mood,''), created_at, updated_at FROM diary_old",
            (default,),
        )
        conn.execute("DROP TABLE diary_old")

    # instruments：PK(id) → PK(member_id, id)（重建小表）
    icols = {r[1] for r in conn.execute("PRAGMA table_info(instruments)").fetchall()}
    if icols and "updated_at" in icols:
        pk = [r[1] for r in conn.execute("PRAGMA table_info(instruments)").fetchall() if r[5]]
        if pk != ["member_id", "id"]:
            conn.execute("ALTER TABLE instruments RENAME TO instruments_old")
            conn.executescript(
                "CREATE TABLE instruments (member_id INTEGER NOT NULL DEFAULT 1, id TEXT NOT NULL,"
                " type TEXT NOT NULL, name TEXT NOT NULL, code TEXT NOT NULL DEFAULT '',"
                " benchmark_index TEXT NOT NULL DEFAULT '', benchmark_tr_code TEXT NOT NULL DEFAULT '',"
                " account TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL, PRIMARY KEY (member_id, id));"
            )
            has_member = "member_id" in icols
            if has_member:
                conn.execute(
                    "INSERT INTO instruments(member_id, id, type, name, code, benchmark_index, benchmark_tr_code, account, updated_at)"
                    " SELECT member_id, id, type, name, IFNULL(code,''), IFNULL(benchmark_index,''), IFNULL(benchmark_tr_code,''), IFNULL(account,''), updated_at FROM instruments_old"
                )
            else:
                conn.execute(
                    "INSERT INTO instruments(member_id, id, type, name, code, benchmark_index, benchmark_tr_code, account, updated_at)"
                    " SELECT ?, id, type, name, IFNULL(code,''), IFNULL(benchmark_index,''), IFNULL(benchmark_tr_code,''), IFNULL(account,''), updated_at FROM instruments_old",
                    (default,),
                )
            conn.execute("DROP TABLE instruments_old")


class LocalStore:
    #: 迁移按库文件只跑一次（进程内缓存——每请求都会构造 store，迁移语句
    #: 反复执行会与后台线程（周报/拉数）产生 SQLite 写锁竞争，2026-11-08 实证）
    _migrated: set[str] = set()

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        key = str(self.db_path.resolve())
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            if key not in LocalStore._migrated:
                _migrate_member_columns(conn)
                LocalStore._migrated.add(key)
        # WAL 只在初始化设置一次（持久化于库文件）：逐连接执行 journal_mode
        # 需要独占锁，与后台线程（周报/拉数）并发时必现 database is locked
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA busy_timeout=10000")
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

    def series_updated_at(self, instrument: str, kind: str) -> str | None:
        """序列缓存最后刷新时间（S05 stale 判定用）；无数据返回 None。"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT MAX(updated_at) FROM series WHERE instrument=? AND kind=?",
                (instrument, kind),
            ).fetchone()
        return row[0] if row else None

    # ---- 中证指数目录 ----

    def upsert_catalog(self, code_name: pd.DataFrame) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        rows = [
            (r.index_code, r.name, r.full_name, now) for r in code_name.itertuples()
        ]
        with self._conn() as conn:
            conn.executemany("INSERT OR REPLACE INTO csi_catalog VALUES (?,?,?,?)", rows)
        return len(rows)

    # ---- 信号留痕（S11：member 维度） ----

    def add_signals(self, signals: list, member_id: int | None = None) -> list[int]:
        """落库（同会员同日同标的同规则同动作去重），返回新增行的 id 列表。"""
        mid = member_id if member_id is not None else default_member_id()
        now = datetime.now().isoformat(timespec="seconds")
        new_ids: list[int] = []
        with self._conn() as conn:
            for s in signals:
                dup = conn.execute(
                    "SELECT id FROM signals WHERE member_id=? AND date=? AND instrument_id=? AND rule_ref=? AND action=?",
                    (mid, s.date, s.instrument_id, s.rule_ref, s.action),
                ).fetchone()
                if dup:
                    continue
                cur = conn.execute(
                    "INSERT INTO signals(member_id, date, instrument_id, rule_ref, metric, metric_value, action, status, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (mid, s.date, s.instrument_id, s.rule_ref, s.metric, s.metric_value, s.action, s.status, now),
                )
                new_ids.append(cur.lastrowid)
        return new_ids

    def recent_signals(self, member_id: int | None = None, limit: int = 10, status: str | None = None) -> list[tuple]:
        """最近信号（默认会员）；status 传入则只取该状态（如总览页只显示活跃的'建议'）。"""
        mid = member_id if member_id is not None else default_member_id()
        sql = "SELECT id, date, instrument_id, rule_ref, metric, metric_value, action, status FROM signals WHERE member_id=?"
        params: tuple = (mid,)
        if status:
            sql += " AND status = ?"
            params = params + (status,)
        sql += " ORDER BY id DESC LIMIT ?"
        with self._conn() as conn:
            return conn.execute(sql, params + (limit,)).fetchall()

    def update_signal_status(self, signal_id: int, status: str, member_id: int | None = None) -> bool:
        """更新信号状态；member_id 传入时校验归属（越权返回 False 等价 404）。"""
        sql = "UPDATE signals SET status=? WHERE id=?"
        params: tuple = (status, signal_id)
        if member_id is not None:
            sql += " AND member_id=?"
            params = params + (member_id,)
        with self._conn() as conn:
            cur = conn.execute(sql, params)
            return cur.rowcount > 0

    # ---- 投资日记（R5；S11：member 维度） ----

    def upsert_diary(self, date: str, content: str, mood: str = "", member_id: int | None = None) -> bool:
        mid = member_id if member_id is not None else default_member_id()
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO diary(member_id, date, content, mood, created_at, updated_at) VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(member_id, date) DO UPDATE SET content=excluded.content, mood=excluded.mood, updated_at=excluded.updated_at",
                (mid, date, content, mood, now, now),
            )
            return cur.rowcount > 0

    def delete_diary(self, date: str, member_id: int | None = None) -> bool:
        mid = member_id if member_id is not None else default_member_id()
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM diary WHERE member_id=? AND date=?", (mid, date))
            return cur.rowcount > 0

    def list_diary(self, member_id: int | None = None, limit: int = 50) -> list[tuple]:
        mid = member_id if member_id is not None else default_member_id()
        with self._conn() as conn:
            return conn.execute(
                "SELECT date, content, mood, updated_at FROM diary WHERE member_id=? ORDER BY date DESC LIMIT ?", (mid, limit)
            ).fetchall()

    def get_diary(self, date: str, member_id: int | None = None) -> tuple | None:
        mid = member_id if member_id is not None else default_member_id()
        with self._conn() as conn:
            return conn.execute(
                "SELECT date, content, mood, updated_at FROM diary WHERE member_id=? AND date=?", (mid, date)
            ).fetchone()

    # ---- 标的管理（S2：小程序端 CRUD，yaml 仅作种子；S11：member 维度） ----

    def upsert_instrument(self, row: dict, member_id: int | None = None) -> None:
        mid = member_id if member_id is not None else default_member_id()
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO instruments(member_id, id, type, name, code, benchmark_index, benchmark_tr_code, account, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(member_id, id) DO UPDATE SET type=excluded.type, name=excluded.name, code=excluded.code,"
                " benchmark_index=excluded.benchmark_index, benchmark_tr_code=excluded.benchmark_tr_code,"
                " account=excluded.account, updated_at=excluded.updated_at",
                (mid, row["id"], row["type"], row["name"], row.get("code", ""),
                 row.get("benchmark_index", ""), row.get("benchmark_tr_code", ""),
                 row.get("account", ""), now),
            )

    def delete_instrument(self, ins_id: str, member_id: int | None = None) -> bool:
        mid = member_id if member_id is not None else default_member_id()
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM instruments WHERE member_id=? AND id=?", (mid, ins_id))
            return cur.rowcount > 0

    def list_instruments(self, member_id: int | None = None) -> list[tuple]:
        """member_id=None 返回全部会员合并视图（调度器/CLI 拉数用），否则仅该会员。"""
        with self._conn() as conn:
            if member_id is None:
                return conn.execute(
                    "SELECT id, type, name, code, benchmark_index, benchmark_tr_code, account FROM instruments ORDER BY id"
                ).fetchall()
            return conn.execute(
                "SELECT id, type, name, code, benchmark_index, benchmark_tr_code, account FROM instruments WHERE member_id=? ORDER BY id",
                (member_id,),
            ).fetchall()

    # ---- 交易流水（S11：CSV 迁库，member 维度；CSV 保留为导出格式） ----

    def append_trades(self, member_id: int, rows: list[dict]) -> int:
        """批量追加流水，返回写入行数。rows: [{date, instrument_id, action, quantity, price, fee?, note?}]"""
        now = datetime.now().isoformat(timespec="seconds")
        data = [
            (member_id, r["date"], r["instrument_id"], r["action"],
             float(r["quantity"]), float(r["price"]), float(r.get("fee") or 0), str(r.get("note") or ""), now)
            for r in rows
        ]
        with self._conn() as conn:
            conn.executemany(
                "INSERT INTO trades(member_id, date, instrument_id, action, quantity, price, fee, note, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                data,
            )
        return len(data)

    def list_trades(self, member_id: int, instrument_id: str | None = None) -> list[dict]:
        """会员流水（含自增 id），旧→新；instrument_id 传入则过滤。"""
        sql = "SELECT id, date, instrument_id, action, quantity, price, fee, note FROM trades WHERE member_id=?"
        params: tuple = (member_id,)
        if instrument_id:
            sql += " AND instrument_id=?"
            params = params + (instrument_id,)
        sql += " ORDER BY date, id"
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            {"id": r[0], "date": r[1], "instrument_id": r[2], "action": r[3],
             "quantity": r[4], "price": r[5], "fee": r[6], "note": r[7]}
            for r in rows
        ]

    def delete_trade(self, member_id: int, trade_id: int) -> bool:
        """按 id 删除（member 归属校验内置，越权等价不存在）。"""
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM trades WHERE member_id=? AND id=?", (member_id, trade_id))
            return cur.rowcount > 0

    def delete_trade_row(self, member_id: int, row: dict) -> bool:
        """按整行内容删除（旧客户端兼容）：数值列容差、空值归一（与 CSV 时代同口径）。"""
        from ..ledger.trades import _row_matches

        for r in self.list_trades(member_id):
            if _row_matches({k: str(v) for k, v in r.items() if k != "id"}, row):
                return self.delete_trade(member_id, r["id"])
        return False

    def trade_count(self, member_id: int) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) FROM trades WHERE member_id=?", (member_id,)).fetchone()
        return int(row[0])

    def member_ids_with_trades(self) -> list[int]:
        """有流水的会员清单（调度器逐会员评估信号用）。"""
        with self._conn() as conn:
            return [int(r[0]) for r in conn.execute("SELECT DISTINCT member_id FROM trades ORDER BY member_id").fetchall()]

    # ---- 审计（S11 AC-6：who/what/when/traceId，不含金额明文） ----

    def add_audit(self, member_id: int, action: str, detail: str = "", trace_id: str = "") -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO audit_log(member_id, action, detail, trace_id, created_at) VALUES (?,?,?,?,?)",
                (member_id, action, detail, trace_id, now),
            )

    def list_audit(self, limit: int = 100, member_id: int | None = None) -> list[tuple]:
        sql = "SELECT id, member_id, action, detail, trace_id, created_at FROM audit_log"
        params: tuple = ()
        if member_id is not None:
            sql += " WHERE member_id=?"
            params = (member_id,)
        sql += " ORDER BY id DESC LIMIT ?"
        with self._conn() as conn:
            return conn.execute(sql, params + (limit,)).fetchall()

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
