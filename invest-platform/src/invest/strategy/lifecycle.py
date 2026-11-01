"""信号生命周期 + 纸面交易存储层（S02-B/S02-C，spec-S02-strategy-engine.md）。

信号状态机：generated → confirmed（→ 纸面交易 open → closed）/ ignored / expired(7天)。
纸面交易仅记录虚拟操作（红线：不产生真实交易）；收益率为方向化小数
（buy = close/entry − 1；sell = entry/close − 1，价跌才盈利）。

表名用 signal_records/paper_trades——**刻意避开 LocalStore/MySQLStore 已有的
signals 旧表**（v0.6 同名不同构，CREATE TABLE IF NOT EXISTS 会静默保留旧表，
新列写入直接炸裂）。DDL 只用双端兼容写法（VARCHAR/REAL、表内约束、无
AUTOINCREMENT/PRAGMA），SQLite 直接可建，MySQL 亦可执行。

SQL 纪律：源码一律 ? 占位符、零拼接；遇到 pymysql 连接由 _execute 自动
译成 %s / INSERT IGNORE（MySQL 方言），调用方无感。
"""
from __future__ import annotations

import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

#: 生命周期状态（spec S02-C）
SIGNAL_STATUSES = ("generated", "confirmed", "ignored", "expired")

_DDL = """
CREATE TABLE IF NOT EXISTS signal_records (
    id VARCHAR(64) PRIMARY KEY,
    instrument_id VARCHAR(64) NOT NULL,
    final_signal VARCHAR(16) NOT NULL,
    confidence REAL NOT NULL,
    summary TEXT NOT NULL,
    status VARCHAR(16) NOT NULL,
    created_at VARCHAR(32) NOT NULL,
    confirmed_at VARCHAR(32),
    results_json TEXT NOT NULL,
    UNIQUE (instrument_id, final_signal, created_at)
);
CREATE TABLE IF NOT EXISTS paper_trades (
    id VARCHAR(64) PRIMARY KEY,
    signal_id VARCHAR(64) NOT NULL,
    instrument_id VARCHAR(64) NOT NULL,
    action VARCHAR(16) NOT NULL,
    quantity REAL NOT NULL,
    price_at_signal REAL NOT NULL,
    status VARCHAR(16) NOT NULL,
    created_at VARCHAR(32) NOT NULL,
    closed_at VARCHAR(32),
    close_price REAL,
    return_pct REAL
);
"""

_SIGNAL_COLS = ("id, instrument_id, final_signal, confidence, summary, status,"
                " created_at, confirmed_at, results_json")
_PAPER_COLS = ("id, signal_id, instrument_id, action, quantity, price_at_signal,"
               " status, created_at, closed_at, close_price, return_pct")


def _now() -> str:
    """统一时间戳：ISO 精确到秒（TEXT 字典序 = 时间序，过期判断可直接比较）。"""
    return datetime.now().isoformat(timespec="seconds")


def directional_return(action: str, entry_price: float, price: float) -> float:
    """方向化收益率（小数）：buy=price/entry−1；sell=entry/price−1（价跌盈利）。

    入价/现价非法（<=0）返回 0.0——脏数据不应炸掉批量刷新。
    """
    if entry_price <= 0 or price <= 0:
        return 0.0
    if action == "sell":
        return entry_price / price - 1.0
    return price / entry_price - 1.0


@dataclass
class SignalRecord:
    """一条综合信号的留痕（strategy.engine.CompositeSignal 的落库形态）。"""

    id: str = ""  # 缺省由 save_signal 生成 sig_<uuid12>
    instrument_id: str = ""
    final_signal: str = "hold"
    confidence: float = 0.0
    summary: str = ""
    status: str = "generated"
    created_at: str = ""  # ISO；缺省当前时间
    results_json: str = "[]"  # 各规则命中明细（RuleResult 序列化，由调用方生成）
    confirmed_at: str | None = None  # 确认时间（API 响应字段）

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = _now()


@dataclass
class PaperTrade:
    """纸面交易：信号确认后的虚拟操作，仅记录跟踪，非真实交易。"""

    id: str = ""  # 缺省由 save_paper 生成 pt_<uuid12>
    signal_id: str = ""
    instrument_id: str = ""
    action: str = "buy"  # buy | sell
    quantity: float = 0.0
    price_at_signal: float = 0.0  # 入场价（信号时刻价格）
    status: str = "open"  # open | closed
    created_at: str = ""
    closed_at: str | None = None
    close_price: float | None = None
    return_pct: float | None = None  # 方向化小数收益率（0.05 = +5%）

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = _now()

    def close(self, close_price: float) -> float:
        """平仓：计算方向化收益并落字段（status→closed），返回 return_pct。"""
        self.close_price = float(close_price)
        self.return_pct = directional_return(self.action, self.price_at_signal, close_price)
        self.status = "closed"
        self.closed_at = _now()
        return self.return_pct


class SignalLifecycleStore:
    """信号生命周期 + 纸面交易存储。

    store 入参（三选一）：带 .conn 的对象（连接复用）/ 带 .db_path 的
    LocalStore（自动开 SQLite 连接）/ sqlite3 连接对象本身。
    """

    def __init__(self, store):
        self.conn = self._resolve_conn(store)
        # FastAPI async 路由跑在事件循环线程、构造可能在别的线程：自开连接放行跨线程，
        # 并以可重入锁串行化全部 SQL（跨线程共享单连接必须串行）
        self._lock = threading.RLock()
        self._init_tables()

    @staticmethod
    def _resolve_conn(store) -> sqlite3.Connection:
        """取可用连接：.conn 优先，LocalStore 走 db_path，也接受裸连接。

        自开的 SQLite 连接带 check_same_thread=False（Web 端 async 路由跨线程用）；
        外部传入的 .conn 由提供方负责线程语义（sqlite 需在建连时同样放行）。
        """
        conn = getattr(store, "conn", None)
        if conn is not None:
            return conn
        db_path = getattr(store, "db_path", None)
        if db_path is not None:  # LocalStore：复用其 SQLite 文件（WAL 已由其建库时设置）
            return sqlite3.connect(str(db_path), check_same_thread=False)
        if isinstance(store, sqlite3.Connection):
            return store
        raise TypeError("SignalLifecycleStore 需要带 .conn 或 .db_path 的 store，或直接传 sqlite3 连接")

    # ---- SQL 方言适配：源码 ? 占位符，pymysql 自动转 %s / INSERT IGNORE ----

    def _execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        with self._lock:
            if isinstance(self.conn, sqlite3.Connection):
                return self.conn.execute(sql, tuple(params))
            cur = self.conn.cursor()
            adapted = sql.replace("INSERT OR IGNORE", "INSERT IGNORE").replace("?", "%s")
            return cur.execute(adapted, tuple(params))

    def _init_tables(self) -> None:
        """建 signal_records + paper_trades 表（幂等；约束用双端兼容的表内写法）。"""
        with self._lock:
            for stmt in (s.strip() for s in _DDL.split(";")):
                if stmt:
                    self._execute(stmt)
            self.conn.commit()

    # ---- 信号生命周期 ----

    def save_signal(self, sig: SignalRecord) -> str:
        """落库（同标的同信号同秒去重，INSERT OR IGNORE），返回实际行的 id。

        撞唯一键被忽略时回填并返回已有行的 id——调用方拿到的 id 始终指向库内真实行。
        """
        with self._lock:
            if not sig.id:
                sig.id = f"sig_{uuid.uuid4().hex[:12]}"
            cur = self._execute(
                f"INSERT OR IGNORE INTO signal_records ({_SIGNAL_COLS}) VALUES (?,?,?,?,?,?,?,?,?)",
                (sig.id, sig.instrument_id, sig.final_signal, float(sig.confidence),
                 sig.summary, sig.status, sig.created_at, sig.confirmed_at, sig.results_json),
            )
            if cur.rowcount == 0:  # 撞唯一键被忽略 → 找回已有行 id
                row = self._execute(
                    "SELECT id FROM signal_records WHERE instrument_id=? AND final_signal=? AND created_at=?",
                    (sig.instrument_id, sig.final_signal, sig.created_at),
                ).fetchone()
                if row:
                    sig.id = row[0]
            self.conn.commit()
            return sig.id

    def confirm(self, signal_id: str) -> bool:
        """generated → confirmed（记录确认时间）；不存在或已操作返回 False。"""
        with self._lock:
            cur = self._execute(
                "UPDATE signal_records SET status='confirmed', confirmed_at=? WHERE id=? AND status='generated'",
                (_now(), signal_id),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def ignore(self, signal_id: str) -> bool:
        """generated → ignored；不存在或已操作返回 False。"""
        with self._lock:
            cur = self._execute(
                "UPDATE signal_records SET status='ignored' WHERE id=? AND status='generated'",
                (signal_id,),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def expire_stale(self, days: int = 7) -> int:
        """超期（默认7天）未操作的 generated 信号批量过期，返回影响行数。"""
        with self._lock:
            cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
            cur = self._execute(
                "UPDATE signal_records SET status='expired' WHERE status='generated' AND created_at < ?",
                (cutoff,),
            )
            self.conn.commit()
            return cur.rowcount

    def list_signals(self, status: str = "", limit: int = 50) -> list[SignalRecord]:
        """按创建时间倒序列信号；status 传空取全部状态。"""
        with self._lock:
            sql = f"SELECT {_SIGNAL_COLS} FROM signal_records"
            params: list = []
            if status:
                sql += " WHERE status=?"
                params.append(status)
            sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
            params.append(limit)
            rows = self._execute(sql, params).fetchall()
            return [SignalRecord(
                id=r[0], instrument_id=r[1], final_signal=r[2], confidence=float(r[3]),
                summary=r[4] or "", status=r[5], created_at=r[6],
                confirmed_at=r[7], results_json=r[8] or "[]",
            ) for r in rows]

    # ---- 纸面交易 ----

    def save_paper(self, trade: PaperTrade) -> str:
        """落库（INSERT OR IGNORE），返回交易 id。"""
        with self._lock:
            if not trade.id:
                trade.id = f"pt_{uuid.uuid4().hex[:12]}"
            self._execute(
                f"INSERT OR IGNORE INTO paper_trades ({_PAPER_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (trade.id, trade.signal_id, trade.instrument_id, trade.action,
                 float(trade.quantity), float(trade.price_at_signal), trade.status,
                 trade.created_at, trade.closed_at, trade.close_price, trade.return_pct),
            )
            self.conn.commit()
            return trade.id

    def get_paper(self, trade_id: str) -> PaperTrade | None:
        with self._lock:
            row = self._execute(
                f"SELECT {_PAPER_COLS} FROM paper_trades WHERE id=?", (trade_id,)
            ).fetchone()
            return self._row_to_paper(row) if row else None

    def close_paper(self, trade_id: str, close_price: float) -> bool:
        """关闭 open 状态的纸面交易并落收益（PaperTrade.close 口径）；非 open 返回 False。"""
        with self._lock:
            trade = self.get_paper(trade_id)
            if trade is None or trade.status != "open":
                return False
            trade.close(close_price)
            cur = self._execute(
                "UPDATE paper_trades SET status=?, closed_at=?, close_price=?, return_pct=?"
                " WHERE id=? AND status='open'",
                (trade.status, trade.closed_at, trade.close_price, trade.return_pct, trade_id),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def list_papers(self, status: str = "", limit: int = 50) -> list[PaperTrade]:
        """按创建时间倒序列纸面交易；status 传空取全部状态。"""
        with self._lock:
            sql = f"SELECT {_PAPER_COLS} FROM paper_trades"
            params: list = []
            if status:
                sql += " WHERE status=?"
                params.append(status)
            sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
            params.append(limit)
            return [self._row_to_paper(r) for r in self._execute(sql, params).fetchall()]

    def update_returns(self, prices: dict[str, float]) -> int:
        """按最新价批量刷新 open 纸面交易的浮动收益（不改变状态），返回更新条数。

        prices：{instrument_id: 最新价}；不在字典或价格非法（<=0）的标的不动。
        """
        with self._lock:
            rows = self._execute(
                "SELECT id, instrument_id, action, price_at_signal FROM paper_trades WHERE status='open'"
            ).fetchall()
            updated = 0
            for tid, ins_id, action, entry in rows:
                price = prices.get(ins_id)
                if price is None or price <= 0:
                    continue
                cur = self._execute(
                    "UPDATE paper_trades SET return_pct=? WHERE id=? AND status='open'",
                    (directional_return(action, float(entry), float(price)), tid),
                )
                updated += cur.rowcount
            self.conn.commit()
            return updated

    @staticmethod
    def _row_to_paper(r) -> PaperTrade:
        return PaperTrade(
            id=r[0], signal_id=r[1], instrument_id=r[2], action=r[3],
            quantity=float(r[4]), price_at_signal=float(r[5]), status=r[6],
            created_at=r[7], closed_at=r[8],
            close_price=float(r[9]) if r[9] is not None else None,
            return_pct=float(r[10]) if r[10] is not None else None,
        )
