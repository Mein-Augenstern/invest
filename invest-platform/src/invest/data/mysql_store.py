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
    KEY idx_signals_status_id (status, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS diary (
    id INT NOT NULL AUTO_INCREMENT,
    date VARCHAR(16) NOT NULL,
    content TEXT NOT NULL,
    mood VARCHAR(16) NOT NULL DEFAULT '',
    created_at VARCHAR(32) NOT NULL,
    updated_at VARCHAR(32) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_diary_date (date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS instruments (
    id VARCHAR(64) NOT NULL,
    type VARCHAR(16) NOT NULL,
    name VARCHAR(128) NOT NULL,
    code VARCHAR(32) NOT NULL DEFAULT '',
    benchmark_index VARCHAR(32) NOT NULL DEFAULT '',
    benchmark_tr_code VARCHAR(32) NOT NULL DEFAULT '',
    account VARCHAR(64) NOT NULL DEFAULT '',
    updated_at VARCHAR(32) NOT NULL,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


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

    # ---- 信号留痕 ----

    def add_signals(self, signals: list) -> list[int]:
        now = datetime.now().isoformat(timespec="seconds")
        new_ids: list[int] = []
        with self._conn() as conn:
            with conn.cursor() as cur:
                for s in signals:
                    cur.execute(
                        "SELECT id FROM signals WHERE date=%s AND instrument_id=%s "
                        "AND rule_ref=%s AND action=%s",
                        (s.date, s.instrument_id, s.rule_ref, s.action),
                    )
                    if cur.fetchone():
                        continue
                    cur.execute(
                        "INSERT INTO signals(date, instrument_id, rule_ref, metric, metric_value,"
                        " action, status, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                        (s.date, s.instrument_id, s.rule_ref, s.metric, s.metric_value,
                         s.action, s.status, now),
                    )
                    new_ids.append(int(cur.lastrowid))
        return new_ids

    def recent_signals(self, limit: int = 10, status: str | None = None) -> list[tuple]:
        sql = (
            "SELECT id, date, instrument_id, rule_ref, metric, metric_value, action, status"
            " FROM signals"
        )
        params: list = []
        if status:
            sql += " WHERE status = %s"
            params.append(status)
        sql += " ORDER BY id DESC LIMIT %s"
        params.append(limit)
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return [tuple(r) for r in cur.fetchall()]

    def update_signal_status(self, signal_id: int, status: str) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE signals SET status=%s WHERE id=%s", (status, signal_id))
                return cur.rowcount > 0

    # ---- 投资日记 ----

    def upsert_diary(self, date: str, content: str, mood: str = "") -> bool:
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO diary(date, content, mood, created_at, updated_at)"
                    " VALUES (%s,%s,%s,%s,%s)"
                    " ON DUPLICATE KEY UPDATE content=VALUES(content), mood=VALUES(mood),"
                    " updated_at=VALUES(updated_at)",
                    (date, content, mood, now, now),
                )
                return cur.rowcount > 0

    def delete_diary(self, date: str) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM diary WHERE date=%s", (date,))
                return cur.rowcount > 0

    def list_diary(self, limit: int = 50) -> list[tuple]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT date, content, mood, updated_at FROM diary"
                    " ORDER BY date DESC LIMIT %s",
                    (limit,),
                )
                return [tuple(r) for r in cur.fetchall()]

    def get_diary(self, date: str) -> tuple | None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT date, content, mood, updated_at FROM diary WHERE date=%s",
                    (date,),
                )
                row = cur.fetchone()
                return tuple(row) if row else None

    # ---- 标的管理 ----

    def upsert_instrument(self, row: dict) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO instruments(id, type, name, code, benchmark_index,"
                    " benchmark_tr_code, account, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"
                    " ON DUPLICATE KEY UPDATE type=VALUES(type), name=VALUES(name),"
                    " code=VALUES(code), benchmark_index=VALUES(benchmark_index),"
                    " benchmark_tr_code=VALUES(benchmark_tr_code), account=VALUES(account),"
                    " updated_at=VALUES(updated_at)",
                    (row["id"], row["type"], row["name"], row.get("code", ""),
                     row.get("benchmark_index", ""), row.get("benchmark_tr_code", ""),
                     row.get("account", ""), now),
                )

    def delete_instrument(self, ins_id: str) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM instruments WHERE id=%s", (ins_id,))
                return cur.rowcount > 0

    def list_instruments(self) -> list[tuple]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, type, name, code, benchmark_index, benchmark_tr_code, account"
                    " FROM instruments ORDER BY id"
                )
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
