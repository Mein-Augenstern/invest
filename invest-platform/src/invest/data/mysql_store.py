"""MySQL 存储（与 star 系列同一套数据库实例，独立 invest 库）。

- 接口与 LocalStore 逐方法对齐；SQL 全部参数化（%s），无拼接
- 幂等写：REPLACE INTO（等价 SQLite 的 INSERT OR REPLACE）；
  单行 upsert 用 ON DUPLICATE KEY UPDATE
- 连接：pymysql 短连接（单用户低频写，避免 8h wait_timeout 断连态）
- `rank` 是 MySQL 保留字，DDL/SELECT 中以反引号引用
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime

import pandas as pd
import pymysql

SCHEMA = """
CREATE TABLE IF NOT EXISTS series (
    instrument VARCHAR(64) NOT NULL,
    kind VARCHAR(32) NOT NULL,
    date VARCHAR(16) NOT NULL,
    close DOUBLE,
    source VARCHAR(64) NOT NULL DEFAULT '',
    updated_at VARCHAR(32) NOT NULL,
    PRIMARY KEY (instrument, kind, date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS csi_catalog (
    index_code VARCHAR(32) NOT NULL,
    name VARCHAR(128) NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    updated_at VARCHAR(32) NOT NULL,
    PRIMARY KEY (index_code),
    KEY idx_csi_catalog_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS fund_holdings (
    instrument VARCHAR(64) NOT NULL,
    period VARCHAR(16) NOT NULL,
    `rank` INT NOT NULL,
    stock_code VARCHAR(16) NOT NULL,
    stock_name VARCHAR(64) NOT NULL,
    weight DOUBLE NOT NULL,
    updated_at VARCHAR(32) NOT NULL,
    PRIMARY KEY (instrument, period, `rank`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS fund_industry (
    instrument VARCHAR(64) NOT NULL,
    report_date VARCHAR(16) NOT NULL,
    industry VARCHAR(64) NOT NULL,
    weight DOUBLE NOT NULL,
    updated_at VARCHAR(32) NOT NULL,
    PRIMARY KEY (instrument, report_date, industry)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS signals (
    id INT NOT NULL AUTO_INCREMENT,
    member_id INT NOT NULL DEFAULT 1,
    date VARCHAR(16) NOT NULL,
    instrument_id VARCHAR(64) NOT NULL,
    rule_ref VARCHAR(64) NOT NULL,
    metric VARCHAR(64) NOT NULL,
    metric_value VARCHAR(64) NOT NULL,
    action VARCHAR(255) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT '建议',
    created_at VARCHAR(32) NOT NULL,
    PRIMARY KEY (id),
    KEY idx_signals_dedup (date, instrument_id, rule_ref, action),
    KEY idx_signals_status_id (status, id),
    KEY idx_signals_member (member_id, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS diary (
    id INT NOT NULL AUTO_INCREMENT,
    member_id INT NOT NULL DEFAULT 1,
    date VARCHAR(16) NOT NULL,
    content TEXT NOT NULL,
    mood VARCHAR(16) NOT NULL DEFAULT '',
    created_at VARCHAR(32) NOT NULL,
    updated_at VARCHAR(32) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_diary_member_date (member_id, date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS instruments (
    member_id INT NOT NULL DEFAULT 1,
    id VARCHAR(64) NOT NULL,
    type VARCHAR(16) NOT NULL,
    name VARCHAR(128) NOT NULL,
    code VARCHAR(32) NOT NULL DEFAULT '',
    benchmark_index VARCHAR(32) NOT NULL DEFAULT '',
    benchmark_tr_code VARCHAR(32) NOT NULL DEFAULT '',
    account VARCHAR(64) NOT NULL DEFAULT '',
    updated_at VARCHAR(32) NOT NULL,
    PRIMARY KEY (member_id, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS trades (
    id INT NOT NULL AUTO_INCREMENT,
    member_id INT NOT NULL,
    date VARCHAR(16) NOT NULL,
    instrument_id VARCHAR(64) NOT NULL,
    action VARCHAR(32) NOT NULL,
    quantity DOUBLE NOT NULL,
    price DOUBLE NOT NULL,
    fee DOUBLE NOT NULL DEFAULT 0,
    note VARCHAR(255) NOT NULL DEFAULT '',
    created_at VARCHAR(32) NOT NULL,
    PRIMARY KEY (id),
    KEY idx_trades_member_date (member_id, date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS audit_log (
    id INT NOT NULL AUTO_INCREMENT,
    member_id INT NOT NULL,
    action VARCHAR(64) NOT NULL,
    detail VARCHAR(255) NOT NULL DEFAULT '',
    trace_id VARCHAR(64) NOT NULL DEFAULT '',
    created_at VARCHAR(32) NOT NULL,
    PRIMARY KEY (id),
    KEY idx_audit_member (member_id, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS instrument_catalog (
    code VARCHAR(32) NOT NULL,
    name VARCHAR(128) NOT NULL,
    full_name VARCHAR(255) NOT NULL DEFAULT '',
    itype VARCHAR(16) NOT NULL,
    updated_at VARCHAR(32) NOT NULL,
    PRIMARY KEY (code, itype),
    KEY idx_instr_cat_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def _migrate_member_columns(cur) -> None:
    """旧库升级（S11，与 LocalStore 同语义）：补 member_id 列、改唯一/主键、
    历史 NULL 行归并默认会员。幂等可重跑（information_schema 探测）。"""
    from .local import default_member_id

    default = default_member_id()

    def cols(table: str) -> set:
        cur.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s", (table,))
        return {r[0] for r in cur.fetchall()}

    if "member_id" not in cols("signals"):
        cur.execute("ALTER TABLE signals ADD COLUMN member_id INT NULL")
        cur.execute("UPDATE signals SET member_id=%s WHERE member_id IS NULL", (default,))
        cur.execute("ALTER TABLE signals ADD KEY idx_signals_member (member_id, id)")

    if "member_id" not in cols("diary"):
        cur.execute("ALTER TABLE diary ADD COLUMN member_id INT NULL")
        cur.execute("UPDATE diary SET member_id=%s WHERE member_id IS NULL", (default,))
        cur.execute("ALTER TABLE diary DROP INDEX uk_diary_date")
        cur.execute("ALTER TABLE diary ADD UNIQUE KEY uk_diary_member_date (member_id, date)")

    if "member_id" not in cols("instruments"):
        cur.execute("ALTER TABLE instruments ADD COLUMN member_id INT NULL")
        cur.execute("UPDATE instruments SET member_id=%s WHERE member_id IS NULL", (default,))
        cur.execute("ALTER TABLE instruments DROP PRIMARY KEY, ADD PRIMARY KEY (member_id, id)")


def parse_db_url(url: str) -> dict:
    """解析 mysql://user:pass@host:3306/invest 形式的连接串（密码需 URL 编码）。"""
    import urllib.parse

    u = urllib.parse.urlparse(url)
    if u.scheme != "mysql":
        raise ValueError(f"仅支持 mysql:// 连接串，收到: {u.scheme}://")
    return {
        "host": u.hostname or "127.0.0.1",
        "port": u.port or 3306,
        "user": urllib.parse.unquote(u.username or "root"),
        "password": urllib.parse.unquote(u.password or ""),
        "database": u.path.lstrip("/"),
    }


class MySQLStore:
    def __init__(self, host: str, port: int, user: str, password: str, database: str):
        self._cfg = dict(host=host, port=port, user=user, password=password,
                         database=database, charset="utf8mb4", autocommit=False)
        # 建库（若无）+ 建表
        boot = dict(self._cfg)
        dbname = boot.pop("database")
        with pymysql.connect(**boot) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "CREATE DATABASE IF NOT EXISTS `%s` DEFAULT CHARSET utf8mb4"
                    % dbname.replace("`", "")
                )
        with self._conn() as conn:
            for stmt in [s.strip() for s in SCHEMA.split(";") if s.strip()]:
                conn.cursor().execute(stmt)
            _migrate_member_columns(conn.cursor())

    @classmethod
    def from_env(cls, url: str) -> "MySQLStore":
        return cls(**parse_db_url(url))

    @contextmanager
    def _conn(self):
        conn = pymysql.connect(**self._cfg)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---- 时序 ----

    def upsert_series(self, instrument: str, kind: str, df: pd.DataFrame, source: str = "") -> int:
        now = datetime.now().isoformat(timespec="seconds")
        rows = [(instrument, kind, r.date, float(r.close), source, now) for r in df.itertuples()]
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.executemany("REPLACE INTO series VALUES (%s,%s,%s,%s,%s,%s)", rows)
        return len(rows)

    def read_series(self, instrument: str, kind: str) -> pd.DataFrame:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT date, close FROM series WHERE instrument=%s AND kind=%s ORDER BY date",
                    (instrument, kind),
                )
                rows = cur.fetchall()
        return pd.DataFrame(rows, columns=["date", "close"])

    def latest(self, instrument: str, kind: str) -> tuple[str, float] | None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT date, close FROM series WHERE instrument=%s AND kind=%s "
                    "ORDER BY date DESC LIMIT 1",
                    (instrument, kind),
                )
                row = cur.fetchone()
        return (row[0], row[1]) if row else None

    def series_updated_at(self, instrument: str, kind: str) -> str | None:
        """序列缓存最后刷新时间（S05 stale 判定用，与 LocalStore 对齐）；无数据返回 None。"""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT MAX(updated_at) FROM series WHERE instrument=%s AND kind=%s",
                    (instrument, kind),
                )
                row = cur.fetchone()
        return row[0] if row else None

    # ---- 中证指数目录 ----

    def upsert_catalog(self, code_name: pd.DataFrame) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        rows = [(r.index_code, r.name, r.full_name, now) for r in code_name.itertuples()]
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.executemany("REPLACE INTO csi_catalog VALUES (%s,%s,%s,%s)", rows)
        return len(rows)

    def resolve_index_code(self, name: str) -> str | None:
        fuzzy = f"%{name}%"
        with self._conn() as conn:
            with conn.cursor() as cur:
                for sql, param in (
                    ("SELECT index_code FROM csi_catalog WHERE name = %s LIMIT 1", name),
                    ("SELECT index_code FROM csi_catalog WHERE full_name LIKE %s LIMIT 1", fuzzy),
                    ("SELECT index_code FROM csi_catalog WHERE name LIKE %s LIMIT 1", fuzzy),
                ):
                    cur.execute(sql, (param,))
                    row = cur.fetchone()
                    if row:
                        return row[0]
        return None

    # ---- 信号留痕（S11：member 维度） ----

    def add_signals(self, signals: list, member_id: int | None = None) -> list[int]:
        from .local import default_member_id

        mid = member_id if member_id is not None else default_member_id()
        now = datetime.now().isoformat(timespec="seconds")
        new_ids: list[int] = []
        with self._conn() as conn:
            with conn.cursor() as cur:
                for s in signals:
                    cur.execute(
                        "SELECT id FROM signals WHERE member_id=%s AND date=%s AND instrument_id=%s AND rule_ref=%s AND action=%s",
                        (mid, s.date, s.instrument_id, s.rule_ref, s.action),
                    )
                    if cur.fetchone():
                        continue
                    cur.execute(
                        "INSERT INTO signals(member_id, date, instrument_id, rule_ref, metric, metric_value, action, status, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (mid, s.date, s.instrument_id, s.rule_ref, s.metric, s.metric_value, s.action, s.status, now),
                    )
                    new_ids.append(int(cur.lastrowid))
        return new_ids

    def recent_signals(self, member_id: int | None = None, limit: int = 10, status: str | None = None) -> list[tuple]:
        from .local import default_member_id

        mid = member_id if member_id is not None else default_member_id()
        sql = "SELECT id, date, instrument_id, rule_ref, metric, metric_value, action, status FROM signals WHERE member_id=%s"
        params: list = [mid]
        if status:
            sql += " AND status = %s"
            params.append(status)
        sql += " ORDER BY id DESC LIMIT %s"
        params.append(limit)
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return [tuple(r) for r in cur.fetchall()]

    def update_signal_status(self, signal_id: int, status: str, member_id: int | None = None) -> bool:
        sql = "UPDATE signals SET status=%s WHERE id=%s"
        params: list = [status, signal_id]
        if member_id is not None:
            sql += " AND member_id=%s"
            params.append(member_id)
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.rowcount > 0

    # ---- 投资日记（S11：member 维度） ----

    def upsert_diary(self, date: str, content: str, mood: str = "", member_id: int | None = None) -> bool:
        from .local import default_member_id

        mid = member_id if member_id is not None else default_member_id()
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO diary(member_id, date, content, mood, created_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE content=VALUES(content), mood=VALUES(mood), updated_at=VALUES(updated_at)",
                    (mid, date, content, mood, now, now),
                )
                return cur.rowcount > 0

    def delete_diary(self, date: str, member_id: int | None = None) -> bool:
        from .local import default_member_id

        mid = member_id if member_id is not None else default_member_id()
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM diary WHERE member_id=%s AND date=%s", (mid, date))
                return cur.rowcount > 0

    def list_diary(self, member_id: int | None = None, limit: int = 50) -> list[tuple]:
        from .local import default_member_id

        mid = member_id if member_id is not None else default_member_id()
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT date, content, mood, updated_at FROM diary WHERE member_id=%s ORDER BY date DESC LIMIT %s",
                    (mid, limit),
                )
                return [tuple(r) for r in cur.fetchall()]

    def get_diary(self, date: str, member_id: int | None = None) -> tuple | None:
        from .local import default_member_id

        mid = member_id if member_id is not None else default_member_id()
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT date, content, mood, updated_at FROM diary WHERE member_id=%s AND date=%s",
                    (mid, date),
                )
                row = cur.fetchone()
                return tuple(row) if row else None

    # ---- 标的管理（S11：member 维度） ----

    def upsert_instrument(self, row: dict, member_id: int | None = None) -> None:
        from .local import default_member_id

        mid = member_id if member_id is not None else default_member_id()
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO instruments(member_id, id, type, name, code, benchmark_index, benchmark_tr_code, account, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE type=VALUES(type), name=VALUES(name), code=VALUES(code), benchmark_index=VALUES(benchmark_index), benchmark_tr_code=VALUES(benchmark_tr_code), account=VALUES(account), updated_at=VALUES(updated_at)",
                    (mid, row["id"], row["type"], row["name"], row.get("code", ""),
                     row.get("benchmark_index", ""), row.get("benchmark_tr_code", ""),
                     row.get("account", ""), now),
                )

    def delete_instrument(self, ins_id: str, member_id: int | None = None) -> bool:
        from .local import default_member_id

        mid = member_id if member_id is not None else default_member_id()
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM instruments WHERE member_id=%s AND id=%s", (mid, ins_id))
                return cur.rowcount > 0

    def list_instruments(self, member_id: int | None = None) -> list[tuple]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                if member_id is None:
                    cur.execute(
                        "SELECT id, type, name, code, benchmark_index, benchmark_tr_code, account FROM instruments ORDER BY id"
                    )
                else:
                    cur.execute(
                        "SELECT id, type, name, code, benchmark_index, benchmark_tr_code, account FROM instruments WHERE member_id=%s ORDER BY id",
                        (member_id,),
                    )
                return [tuple(r) for r in cur.fetchall()]

    # ---- 交易流水（S11：CSV 迁库，member 维度） ----

    def append_trades(self, member_id: int, rows: list[dict]) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        data = [
            (member_id, r["date"], r["instrument_id"], r["action"],
             float(r["quantity"]), float(r["price"]), float(r.get("fee") or 0), str(r.get("note") or ""), now)
            for r in rows
        ]
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO trades(member_id, date, instrument_id, action, quantity, price, fee, note, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    data,
                )
        return len(data)

    def list_trades(self, member_id: int, instrument_id: str | None = None) -> list[dict]:
        sql = "SELECT id, date, instrument_id, action, quantity, price, fee, note FROM trades WHERE member_id=%s"
        params: list = [member_id]
        if instrument_id:
            sql += " AND instrument_id=%s"
            params.append(instrument_id)
        sql += " ORDER BY date, id"
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return [
            {"id": r[0], "date": r[1], "instrument_id": r[2], "action": r[3],
             "quantity": r[4], "price": r[5], "fee": r[6], "note": r[7]}
            for r in rows
        ]

    def delete_trade(self, member_id: int, trade_id: int) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM trades WHERE member_id=%s AND id=%s", (member_id, trade_id))
                return cur.rowcount > 0

    def delete_trade_row(self, member_id: int, row: dict) -> bool:
        from ..ledger.trades import _row_matches

        for r in self.list_trades(member_id):
            if _row_matches({k: str(v) for k, v in r.items() if k != "id"}, row):
                return self.delete_trade(member_id, r["id"])
        return False

    def trade_count(self, member_id: int) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM trades WHERE member_id=%s", (member_id,))
                return int(cur.fetchone()[0])

    def member_ids_with_trades(self) -> list[int]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT member_id FROM trades ORDER BY member_id")
                return [int(r[0]) for r in cur.fetchall()]

    def browse_catalog(self, itype: str = "", page: int = 1, page_size: int = 50) -> list[tuple]:
        """分页浏览标的目录（品类筛选）。"""
        offset = (page - 1) * page_size
        with self._conn() as conn:
            with conn.cursor() as cur:
                if itype:
                    cur.execute(
                        "SELECT code, name, full_name, itype FROM instrument_catalog WHERE itype = %s ORDER BY code LIMIT %s OFFSET %s",
                        (itype, page_size, offset),
                    )
                else:
                    cur.execute(
                        "SELECT code, name, full_name, itype FROM instrument_catalog ORDER BY itype, code LIMIT %s OFFSET %s",
                        (page_size, offset),
                    )
                return [tuple(r) for r in cur.fetchall()]

    def search_catalog(self, query: str, limit: int = 20) -> list[tuple]:
        """标的目录 + 指数目录统一搜索。返回 (code, name, full_name, itype)。"""
        q = "%" + query + "%"
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT code, name, full_name, itype FROM instrument_catalog WHERE code = %s OR name = %s LIMIT 50", (query, query))
                rows = cur.fetchall()
                if not rows:
                    cur.execute("SELECT code, name, full_name, itype FROM instrument_catalog WHERE name LIKE %s LIMIT 50", (q,))
                    rows = cur.fetchall()
                if rows:
                    return [tuple(r) for r in rows[:limit]]
                for sql, param in (
                    ("SELECT index_code, name, full_name, 'index' FROM csi_catalog WHERE name = %s OR index_code = %s LIMIT 50", (query, query)),
                    ("SELECT index_code, name, full_name, 'index' FROM csi_catalog WHERE name LIKE %s LIMIT 50", (q,)),
                    ("SELECT index_code, name, full_name, 'index' FROM csi_catalog WHERE full_name LIKE %s LIMIT 50", (q,)),
                ):
                    cur.execute(sql, param)
                    rows = cur.fetchall()
                    if rows:
                        return [tuple(r) for r in rows[:limit]]
        return []

    def upsert_catalog_bulk(self, items: list[tuple]) -> int:
        """批量写入标的目录。items: [(code, name, full_name, itype)]"""
        now = datetime.now().isoformat(timespec="seconds")
        data = [(c, n, f, t, now) for c, n, f, t in items]
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    "REPLACE INTO instrument_catalog(code, name, full_name, itype, updated_at) VALUES (%s,%s,%s,%s,%s)",
                    data,
                )
        return len(data)

    def catalog_count(self) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM instrument_catalog")
                return int(cur.fetchone()[0])

    # ---- 审计（S11 AC-6） ----

    def add_audit(self, member_id: int, action: str, detail: str = "", trace_id: str = "") -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO audit_log(member_id, action, detail, trace_id, created_at) VALUES (%s,%s,%s,%s,%s)",
                    (member_id, action, detail, trace_id, now),
                )

    def list_audit(self, limit: int = 100, member_id: int | None = None) -> list[tuple]:
        sql = "SELECT id, member_id, action, detail, trace_id, created_at FROM audit_log"
        params: list = []
        if member_id is not None:
            sql += " WHERE member_id=%s"
            params.append(member_id)
        sql += " ORDER BY id DESC LIMIT %s"
        params.append(limit)
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return [tuple(r) for r in cur.fetchall()]

    # ---- 基金透视 ----

    def upsert_fund_holdings(self, instrument: str, period: str, rows: list[tuple]) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        data = [(instrument, period, r[0], r[1], r[2], float(r[3]), now) for r in rows]
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.executemany("REPLACE INTO fund_holdings VALUES (%s,%s,%s,%s,%s,%s,%s)", data)
        return len(data)

    def fund_holdings(self, instrument: str, period: str | None = None) -> list[tuple]:
        sql = "SELECT `rank`, stock_code, stock_name, weight FROM fund_holdings WHERE instrument=%s"
        params: list = [instrument]
        if period:
            sql += " AND period=%s"
            params.append(period)
        else:
            sql += " AND period=(SELECT MAX(period) FROM fund_holdings WHERE instrument=%s)"
            params.append(instrument)
        sql += " ORDER BY `rank`"
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return [tuple(r) for r in cur.fetchall()]

    def fund_holdings_period(self, instrument: str) -> str | None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT MAX(period) FROM fund_holdings WHERE instrument=%s",
                    (instrument,),
                )
                row = cur.fetchone()
                return row[0] if row else None

    def upsert_fund_industry(self, instrument: str, report_date: str, rows: list[tuple]) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        data = [(instrument, report_date, i[0], float(i[1]), now) for i in rows]
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.executemany("REPLACE INTO fund_industry VALUES (%s,%s,%s,%s,%s)", data)
        return len(data)

    def fund_industry(self, instrument: str) -> list[tuple]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT industry, weight FROM fund_industry WHERE instrument=%s"
                    " AND report_date=(SELECT MAX(report_date) FROM fund_industry"
                    " WHERE instrument=%s) ORDER BY weight DESC",
                    (instrument, instrument),
                )
                return [tuple(r) for r in cur.fetchall()]


def default_store(data_dir):
    """工厂：INVEST_DB_URL=mysql://... 则用 MySQLStore（star 同实例 invest 库），
    否则回落 SQLite（本地开发/测试默认，零依赖）。"""
    url = os.environ.get("INVEST_DB_URL", "")
    if url.startswith("mysql://"):
        return MySQLStore.from_env(url)
    from pathlib import Path

    from invest.data.local import LocalStore

    return LocalStore(Path(data_dir) / "invest.db")
