"""invest 数据迁移：SQLite → MySQL（star 同实例 invest 库）。

用法：
    .venv/bin/python scripts/migrate_to_mysql.py                      # 默认 data/invest.db → INVEST_DB_URL
    .venv/bin/python scripts/migrate_to_mysql.py --from /path/x.db    # 指定源库
目标连接串必须经环境变量注入（公开仓不落任何连接信息）：
    INVEST_DB_URL='mysql://user:pass@host:3306/invest' python scripts/migrate_to_mysql.py
迁移为幂等 upsert（REPLACE/ON DUPLICATE），可重跑；完成后逐表行数校验。
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from invest.data.mysql_store import MySQLStore, parse_db_url

TABLES = ["series", "csi_catalog", "fund_holdings", "fund_industry", "signals", "diary", "instruments"]


class SigRow:
    """add_signals 需要属性访问的行对象。"""

    def __init__(self, r):
        self.date, self.instrument_id, self.rule_ref = r[1], r[2], r[3]
        self.metric, self.metric_value = r[4], r[5]
        self.action, self.status = r[6], r[7] or "建议"


def migrate(src_db: Path, target: MySQLStore) -> dict[str, int]:
    conn = sqlite3.connect(src_db)
    counts: dict[str, int] = {}

    n = 0
    for ins, kind in conn.execute("SELECT DISTINCT instrument, kind FROM series").fetchall():
        df = pd.read_sql_query(
            "SELECT date, close FROM series WHERE instrument=? AND kind=? ORDER BY date",
            conn, params=(ins, kind),
        )
        n += target.upsert_series(ins, kind, df, source=_series_source(conn, ins, kind))
    counts["series"] = n
    counts["csi_catalog"] = _catalog(target, conn)
    counts["fund_holdings"] = _holdings(target, conn)
    counts["fund_industry"] = _industry(target, conn)
    counts["signals"] = _signals(target, conn)
    counts["diary"] = _diary(target, conn)
    counts["instruments"] = _instruments(target, conn)
    conn.close()
    return counts


def _series_source(conn: sqlite3.Connection, ins: str, kind: str) -> str:
    row = conn.execute(
        "SELECT source FROM series WHERE instrument=? AND kind=? AND source!='' LIMIT 1",
        (ins, kind),
    ).fetchone()
    return row[0] if row else ""


def _catalog(target: MySQLStore, conn: sqlite3.Connection) -> int:
    df = pd.read_sql_query("SELECT index_code, name, full_name FROM csi_catalog", conn)
    return target.upsert_catalog(df) if len(df) else 0


def _holdings(target: MySQLStore, conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        "SELECT DISTINCT instrument, period FROM fund_holdings"
    ).fetchall()
    n = 0
    for ins, period in rows:
        data = [
            (r[0], r[1], r[2], r[3])
            for r in conn.execute(
                "SELECT rank, stock_code, stock_name, weight FROM fund_holdings"
                " WHERE instrument=? AND period=? ORDER BY rank",
                (ins, period),
            )
        ]
        n += target.upsert_fund_holdings(ins, period, data)
    return n


def _industry(target: MySQLStore, conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        "SELECT DISTINCT instrument, report_date FROM fund_industry"
    ).fetchall()
    n = 0
    for ins, rd in rows:
        data = [
            (r[0], r[1])
            for r in conn.execute(
                "SELECT industry, weight FROM fund_industry"
                " WHERE instrument=? AND report_date=? ORDER BY weight DESC",
                (ins, rd),
            )
        ]
        n += target.upsert_fund_industry(ins, rd, data)
    return n


def _signals(target: MySQLStore, conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        "SELECT id, date, instrument_id, rule_ref, metric, metric_value, action, status"
        " FROM signals ORDER BY id"
    ).fetchall()
    if not rows:
        return 0
    return len(target.add_signals([SigRow(r) for r in rows]))


def _diary(target: MySQLStore, conn: sqlite3.Connection) -> int:
    rows = conn.execute("SELECT date, content, mood FROM diary ORDER BY date").fetchall()
    n = 0
    for date, content, mood in rows:
        if target.upsert_diary(date, content, mood or ""):
            n += 1
    return n


def _instruments(target: MySQLStore, conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        "SELECT id, type, name, code, benchmark_index, benchmark_tr_code, account"
        " FROM instruments ORDER BY id"
    ).fetchall()
    for r in rows:
        target.upsert_instrument({
            "id": r[0], "type": r[1], "name": r[2], "code": r[3] or "",
            "benchmark_index": r[4] or "", "benchmark_tr_code": r[5] or "",
            "account": r[6] or "",
        })
    return len(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", default=None, help="源 SQLite 路径（默认 data/invest.db）")
    args = ap.parse_args()

    url = os.environ.get("INVEST_DB_URL", "")
    if not url.startswith("mysql://"):
        print("缺少 INVEST_DB_URL（mysql://user:pass@host:3306/invest）")
        return 2
    src = Path(args.src) if args.src else Path(__file__).resolve().parents[1] / "data" / "invest.db"
    if not src.exists():
        print(f"源库不存在: {src}")
        return 2

    target = MySQLStore.from_env(url)
    print(f"迁移 {src} → {parse_db_url(url)['host']}:{parse_db_url(url)['port']}/{parse_db_url(url)['database']}")
    counts = migrate(src, target)

    # 逐表行数校验（标识符无法参数化：全静态字面量映射，零插值零拼接）
    import pymysql

    count_sql = {
        "series": "SELECT COUNT(*) FROM series",
        "csi_catalog": "SELECT COUNT(*) FROM csi_catalog",
        "fund_holdings": "SELECT COUNT(*) FROM fund_holdings",
        "fund_industry": "SELECT COUNT(*) FROM fund_industry",
        "signals": "SELECT COUNT(*) FROM signals",
        "diary": "SELECT COUNT(*) FROM diary",
        "instruments": "SELECT COUNT(*) FROM instruments",
    }
    ok = True
    with target._conn() as tconn:
        with tconn.cursor() as cur:
            sconn = sqlite3.connect(src)
            print(f"{'表':<16}{'源':>8}{'目标':>8}")
            for t, sql in count_sql.items():
                cur.execute(sql)
                dst_n = cur.fetchone()[0]
                src_n = sconn.execute(sql).fetchone()[0]
                mark = "OK" if dst_n >= src_n else "MISS!"
                if dst_n < src_n:
                    ok = False
                print(f"{t:<16}{src_n:>8}{dst_n:>8}  {mark}")
            sconn.close()
    print("迁移完成 ✅" if ok else "存在缺行，检查上方 MISS! ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
