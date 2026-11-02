"""DB 分布式锁（S09，spec docs/sdd/S09-distributed-schedule.md）：定时任务跨实例恰一执行。

与 Java starsite-lock 组件同一套表语义（lock_name 唯一键 + locked_until TTL +
hold_count 计数），表建在 invest 自己的库（SQLite/MySQL 双端兼容 DDL）。多实例
共享同一 DB（Docker 双容器同指 MySQL invest 库）即得互斥——零新中间件，与
XXL-JOB 类调度服务的"中心决策"殊途同归：决策点收敛到 DB 一行。

争锁协议（两步均为单条原子语句，恰一性由 UNIQUE(lock_name) 保证）：
  ① UPDATE … WHERE lock_name=? AND (locked_until IS NULL OR locked_until < now)
     影响行数>0 = 获得锁（首次无主，或 TTL 过期接管崩溃者）
  ② ①未命中且行不存在 → INSERT OR IGNORE 建行抢锁；仍失败 = 他人持有 → 放弃
崩溃自愈（AC-2）：持锁者宕机不释放，locked_until 过 TTL 后被下一轮接管。

SQL 纪律（安全门禁要求）：每条语句在 execute 调用点是单行字符串字面量
（SQLite 用 ? / INSERT OR IGNORE，MySQL 用 %s / INSERT IGNORE），值全部走占位
符参数——不拼、不 format、不 replace、不经变量转手。两步争锁在同一连接内完成，
原子性不依赖跨语句事务。时间戳统一微秒 ISO（TEXT 字典序 = 时间序；微秒精度
避免同秒重复值使 MySQL UPDATE 走 changed-rows 口径出现 0 的假阴性）。
"""
from __future__ import annotations

import os
import socket
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta


def _now_us() -> str:
    """统一时间戳：微秒 ISO（字典序可比较）。"""
    return datetime.now().isoformat(timespec="microseconds")


def _in_minutes(minutes: float) -> str:
    return (datetime.now() + timedelta(minutes=minutes)).isoformat(timespec="microseconds")


def default_holder() -> str:
    """锁持有者标识：hostname:pid（容器形态即 容器名:进程号，日志一眼定位实例）。"""
    return f"{socket.gethostname()}:{os.getpid()}"


@dataclass
class LockState:
    """一把锁的当前状态（/api/schedule/status 观测用）。"""

    lock_name: str
    locked_by: str | None = None
    locked_until: str | None = None
    hold_count: int = 0

    @property
    def held_now(self) -> bool:
        """locked_until 在未来 = 正被持有；NULL / 已过期 = 空闲（可被接管）。"""
        return bool(self.locked_until) and self.locked_until >= _now_us()


class DistributedLock:
    """跨实例互斥锁（非重入：同 holder 持锁期间再 acquire 也返回 False，防重复执行）。

    store 入参：sqlite3 连接（复用，调用方管生命周期）/ 带 .db_path 的 LocalStore
    （每次操作短连接）/ MySQLStore（借其 _conn() 短连接，与全仓 pymysql 模式一致）。
    表名 starsite_lock 与 Java starsite-lock 组件同语义（建在 invest 自己的库）。
    """

    def __init__(self, store, name: str = "invest-pull", *, holder: str = "",
                 ttl_minutes: float = 30.0):
        self.name = name
        self.holder = holder or default_holder()
        self.ttl_minutes = ttl_minutes
        self._sqlite_conn = store if isinstance(store, sqlite3.Connection) else None
        self._db_path = None if self._sqlite_conn is not None else getattr(store, "db_path", None)
        self._mysql_store = None
        if self._sqlite_conn is None and self._db_path is None:
            if callable(getattr(store, "_conn", None)):  # MySQLStore duck-type
                self._mysql_store = store
            else:
                raise TypeError("DistributedLock 需要连接/LocalStore/MySQLStore，或直接传 sqlite3 连接")
        self._is_sqlite = self._mysql_store is None
        # 裸连接可能被多线程共享（async 定时任务 + 手动拉数并发争锁）：操作级串行
        self._guard = threading.Lock()
        with self._conn() as conn:
            if self._is_sqlite:
                conn.execute("CREATE TABLE IF NOT EXISTS starsite_lock (id VARCHAR(64) PRIMARY KEY, lock_name VARCHAR(128) NOT NULL, locked_by VARCHAR(128), locked_until VARCHAR(32), hold_count INT NOT NULL DEFAULT 0, UNIQUE (lock_name))")
                conn.commit()
            else:
                with conn.cursor() as cur:
                    cur.execute("CREATE TABLE IF NOT EXISTS starsite_lock (id VARCHAR(64) PRIMARY KEY, lock_name VARCHAR(128) NOT NULL, locked_by VARCHAR(128), locked_until VARCHAR(32), hold_count INT NOT NULL DEFAULT 0, UNIQUE (lock_name))")

    @contextmanager
    def _conn(self):
        """操作级连接：裸 sqlite 连接复用；store 形态每操作短连接（commit/close 自理）。"""
        if self._sqlite_conn is not None:
            yield self._sqlite_conn
            return
        if self._db_path is not None:
            conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            try:
                yield conn
            finally:
                conn.close()
            return
        with self._mysql_store._conn() as conn:  # noqa: SLF001 - 同仓协作（其 _conn 自带 commit/rollback/close）
            yield conn

    # ---- 争锁协议 ----

    def acquire(self) -> bool:
        """尝试获得锁：成功 True；被他人持有/未释放 False。两步争锁同一连接内完成。"""
        until = _in_minutes(self.ttl_minutes)
        takeover = (self.holder, until, self.name, _now_us())
        create = (f"lock_{uuid.uuid4().hex[:12]}", self.name, self.holder, until)
        with self._guard, self._conn() as conn:
            if self._is_sqlite:
                n = conn.execute("UPDATE starsite_lock SET locked_by=?, locked_until=?, hold_count=hold_count+1 WHERE lock_name=? AND (locked_until IS NULL OR locked_until < ?)", takeover).rowcount
                if not n:  # 行不存在（首次）：建行抢锁；唯一键冲突 = 对手先建 → 恰一
                    n = conn.execute("INSERT OR IGNORE INTO starsite_lock (id, lock_name, locked_by, locked_until, hold_count) VALUES (?,?,?,?,1)", create).rowcount
                conn.commit()
                return n > 0
            with conn.cursor() as cur:
                n = cur.execute("UPDATE starsite_lock SET locked_by=%s, locked_until=%s, hold_count=hold_count+1 WHERE lock_name=%s AND (locked_until IS NULL OR locked_until < %s)", takeover)
                if not n:
                    n = cur.execute("INSERT IGNORE INTO starsite_lock (id, lock_name, locked_by, locked_until, hold_count) VALUES (%s,%s,%s,%s,1)", create)
            return n > 0  # MySQLStore._conn 出口统一 commit

    def release(self) -> bool:
        """释放锁（仅持有者本人可释放；TTL 已被他人接管时不动他人的锁）。"""
        params = (self.name, self.holder)
        with self._guard, self._conn() as conn:
            if self._is_sqlite:
                n = conn.execute("UPDATE starsite_lock SET locked_until=NULL WHERE lock_name=? AND locked_by=?", params).rowcount
                conn.commit()
                return n > 0
            with conn.cursor() as cur:
                n = cur.execute("UPDATE starsite_lock SET locked_until=NULL WHERE lock_name=%s AND locked_by=%s", params)
            return n > 0

    def renew(self) -> bool:
        """续期（长任务防 TTL 内被接管）；非持有者/已被接管时 False。"""
        params = (_in_minutes(self.ttl_minutes), self.name, self.holder)
        with self._guard, self._conn() as conn:
            if self._is_sqlite:
                n = conn.execute("UPDATE starsite_lock SET locked_until=? WHERE lock_name=? AND locked_by=?", params).rowcount
                conn.commit()
                return n > 0
            with conn.cursor() as cur:
                n = cur.execute("UPDATE starsite_lock SET locked_until=%s WHERE lock_name=%s AND locked_by=%s", params)
            return n > 0

    def state(self) -> LockState:
        """当前锁状态（不争锁，纯观测）。"""
        with self._guard, self._conn() as conn:
            if self._is_sqlite:
                row = conn.execute("SELECT locked_by, locked_until, hold_count FROM starsite_lock WHERE lock_name=?", (self.name,)).fetchone()
                if row is not None:
                    conn.commit()
            else:
                with conn.cursor() as cur:
                    cur.execute("SELECT locked_by, locked_until, hold_count FROM starsite_lock WHERE lock_name=%s", (self.name,))
                    row = cur.fetchone()
        if not row:
            return LockState(lock_name=self.name)
        return LockState(self.name, locked_by=row[0], locked_until=row[1], hold_count=int(row[2] or 0))
