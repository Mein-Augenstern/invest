"""定时拉数任务（S09）：分布式锁保护 + 拉数 + 拉完自动评估信号。

恰一执行（AC-1）：多实例同时到点，仅 starsite_lock 争锁成功者执行，其余静默
跳过；持锁者崩溃由 TTL 接管（AC-2，见 distributed_lock.py）。拉完自动评估
信号（AC-3，与手动拉数共用 pull_and_evaluate 核心）；执行留痕进日志与
last_run（AC-5，/api/schedule/status 可观测）。

触发器为零依赖 asyncio 每日循环（FastAPI lifespan 内，INVEST_SCHEDULE=1 开启）：
单个每日任务不值得引入 APScheduler——错过的当次由"次日 20:00 / 手动拉数 /
AC-4 过期自动补拉"兜底。规模化（cron 管理/重试/告警）再迁 XXL-JOB 类服务，
锁协议不变。
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

from .distributed_lock import DistributedLock, LockState, default_holder

logger = logging.getLogger(__name__)

# AC-5 可观测性（2026-11-06 生产验收发现的静默 bug）：容器内无 logging 配置，
# root logger 默认 WARNING 会吞掉全部 INFO——定时拉数的执行痕迹（LOCK/SKIP/DONE）
# 三晚一个字节都没落日志。给 invest 命名空间挂 StreamHandler 并抬到 INFO
# （幂等：已配置过则不动；root 无 handler 故不会重复输出）。
if not logging.getLogger("invest").handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.getLogger("invest").addHandler(_handler)
logging.getLogger("invest").setLevel(logging.INFO)

#: 全平台拉数锁名——双语言协议规范 sch:<app>:<task>（与 Java starsite-schedule 组件
#: 同规范共存于同一 MySQL，可互相观测；Java 侧锁名见组件 LOCK_PREFIX）
LOCK_NAME = "sch:invest:pull"

#: 进程内最近一次定时执行留痕（重启即空；跨实例真相在锁表 + series 数据里）
last_run: dict = {"finished_at": "", "ran": False, "reason": "", "duration_s": 0.0, "evaluated": 0}


def pull_and_evaluate(data_dir, config_path, store, log=print, provider=None) -> int:
    """拉数 + 信号评估一体核心（手动 pulljob / 定时任务共用）。

    store 由调用方注入（default_store：本地 SQLite / 部署 MySQL）——修掉旧
    pulljob 硬编码 LocalStore 的隐性 bug（MySQL 部署下手动拉数写进了容器内
    SQLite，读却走 MySQL，数据永不上屏）。返回新增信号条数；评估失败返回 -1
    （不影响拉数结果）。
    """
    from ..data.akshare_provider import AkshareProvider
    from ..ledger.trades import load_trades
    from ..pipeline import run_pull
    from ..ledger.trades import Trade
    from ..portfolio import load_portfolio
    from ..reporting import evaluate_and_store_signals

    conf = load_portfolio(store, config_path)  # union 视角：拉数覆盖所有在管标的
    run_pull(conf, store, provider or AkshareProvider(), log=log)

    # 标的目录同步（搜标的数据源，S12）：空表首次全量 / 超过 7 天定期刷新。
    # 仅生产（MySQL）执行——本地/测试（SQLite）跳过，避免测试环境网络拉取。
    import os as _os

    if _os.environ.get("INVEST_DB_URL", "").startswith("mysql://"):
        try:
            if _catalog_stale(store):
                _sync_instrument_catalog(store, log)
        except Exception as e:  # noqa: BLE001 - 目录同步失败不影响拉数
            log(f"[WARN] 标的目录同步失败: {type(e).__name__}")
    # S11：逐会员评估（行情是公共缓存，信号/账本是会员的）
    try:
        total = 0
        for mid in store.member_ids_with_trades():
            member_conf = load_portfolio(store, config_path, mid)
            trades = [
                Trade(date=r["date"], instrument_id=r["instrument_id"], action=r["action"],
                      quantity=float(r["quantity"]), price=float(r["price"]),
                      fee=float(r.get("fee") or 0), note=r.get("note") or "")
                for r in store.list_trades(mid)
            ]
            if not trades:
                continue
            total += evaluate_and_store_signals(member_conf, store, trades, member_id=mid)
        log(f"[OK] 信号评估完成（新增 {total} 条）")
        return total
    except Exception as e:  # noqa: BLE001 - 评估失败不影响拉数结果
        log(f"[WARN] 拉数后信号评估失败: {type(e).__name__}")
        return -1


def _catalog_stale(store) -> bool:
    """目录是否需要刷新：空表（首次）或上次同步超过 7 天。"""
    from datetime import datetime, timedelta

    if store.catalog_count() == 0:
        return True
    # 双后端统一接口：取目录最新 updated_at（无此方法时视为不刷新）
    try:
        with store._conn() as conn:
            if hasattr(store, "db_path"):  # SQLite
                row = conn.execute("SELECT MAX(updated_at) FROM instrument_catalog").fetchone()
            else:  # MySQL
                with conn.cursor() as cur:
                    cur.execute("SELECT MAX(updated_at) FROM instrument_catalog")
                    row = cur.fetchone()
        if not row or not row[0]:
            return True
        last = datetime.fromisoformat(row[0])
        return datetime.now() - last > timedelta(days=7)
    except Exception:
        return False


def _sync_instrument_catalog(store, log=print) -> int:
    """标的目录同步（S12 搜索数据源）：akshare 全量清单 → instrument_catalog 表。

    数据源：场外基金 ~28k / ETF ~1.7k / A 股 ~5.6k。首次全量 ~30s。
    """
    items: list[tuple] = []
    import akshare as ak

    try:
        df = ak.stock_info_a_code_name()
        items += [(str(r["code"]), str(r["name"]), str(r["name"]), "stock") for _, r in df.iterrows()]
        log(f"[OK] 标的目录：A 股 {len(df)} 条")
    except Exception as e:
        log(f"[WARN] A 股清单拉取失败: {type(e).__name__}")
    try:
        df = ak.fund_name_em()
        items += [(str(r["基金代码"]), str(r["基金简称"]), str(r["基金简称"]), "fund") for _, r in df.iterrows()]
        log(f"[OK] 标的目录：场外基金 {len(df)} 条")
    except Exception as e:
        log(f"[WARN] 基金清单拉取失败: {type(e).__name__}")
    try:
        df = ak.fund_etf_spot_em()
        items += [(str(r["代码"]), str(r["名称"]), str(r["名称"]), "etf") for _, r in df.iterrows()]
        log(f"[OK] 标的目录：ETF {len(df)} 条")
    except Exception as e:
        log(f"[WARN] ETF 清单拉取失败: {type(e).__name__}")
    if not items:
        return 0
    n = store.upsert_catalog_bulk(items)
    log(f"[OK] 标的目录同步完成：{n} 条（累计 {store.catalog_count()}）")
    return n


def _record(ran: bool, reason: str, started: float, evaluated: int) -> None:
    last_run.update(
        finished_at=datetime.now().isoformat(timespec="seconds"),
        ran=ran, reason=reason,
        duration_s=round(time.monotonic() - started, 1),
        evaluated=evaluated,
    )


def _lock_dict(st: LockState) -> dict:
    return {"name": st.lock_name, "held_by": st.locked_by, "held_now": st.held_now,
            "locked_until": st.locked_until, "hold_count": st.hold_count}


def run_pull_once(data_dir, config_path, *, holder: str = "", ttl_minutes: float = 30.0,
                  log=None, provider=None) -> dict:
    """锁保护的单次"拉数+评估"。

    返回 {"ran": …, "reason": …}：ran=False = 锁被他人持有（正常跳过，非错误，
    多实例恰一执行的另一半）；ran=True 时附带 evaluated/duration_s/lock_holder。
    """
    from ..data.mysql_store import default_store

    started = time.monotonic()
    log = log or (lambda msg: logger.info("[schedule] %s", msg))
    lock = DistributedLock(default_store(data_dir), LOCK_NAME,
                           holder=holder or default_holder(), ttl_minutes=ttl_minutes)
    if not lock.acquire():
        reason = f"lock held by {lock.state().locked_by or 'unknown'}"
        log(f"[SKIP] {reason}")
        _record(False, reason, started, 0)
        return {"ran": False, "reason": reason, "lock": _lock_dict(lock.state())}
    log(f"[LOCK] {lock.holder} 获得锁（TTL {ttl_minutes}min）")
    try:
        evaluated = pull_and_evaluate(data_dir, config_path, default_store(data_dir),
                                      log=log, provider=provider)
        duration = round(time.monotonic() - started, 1)
        log(f"[DONE] 拉数+评估完成：evaluated={evaluated} duration={duration}s")
        _record(True, "", started, evaluated)
        return {"ran": True, "reason": "", "evaluated": evaluated, "duration_s": duration,
                "lock_holder": lock.holder}
    finally:
        if not lock.release():
            log("[WARN] 释放锁失败（锁可能已被 TTL 接管）")


def _now_cn() -> datetime:
    """触发计算用北京时间（产品语义：A股/基金日级周期；TZ 缺 tzdata 时退本地钟）。"""
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Shanghai"))
    except Exception:  # noqa: BLE001 - 镜像无 tzdata 时退化为容器本地时钟
        return datetime.now()


def next_run_at(now: datetime, hour: int, minute: int) -> datetime:
    """下一个触发时刻（今天未到 = 今天，否则明天）。纯函数可测。"""
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def _cron_from_env() -> tuple[int, int, float]:
    """(hour, minute, ttl_minutes)：默认每天 20:00（基金净值发布后），TTL 30 分钟。"""
    return (int(os.environ.get("INVEST_PULL_HOUR", "20")),
            int(os.environ.get("INVEST_PULL_MINUTE", "0")),
            float(os.environ.get("INVEST_PULL_LOCK_TTL_MIN", "30")))


def schedule_enabled() -> bool:
    return os.environ.get("INVEST_SCHEDULE", "").lower() in ("1", "true", "yes", "on")


async def schedule_loop(app) -> None:
    """每日循环（lifespan 内 create_task）：睡到触发点 → 线程池执行（拉数是同步网络 IO）。"""
    hour, minute, ttl = _cron_from_env()
    logger.info("定时拉数已启用：每天 %02d:%02d 北京时间（锁 %s，TTL %gmin）", hour, minute, LOCK_NAME, ttl)
    while True:
        now = _now_cn()
        delay = (next_run_at(now, hour, minute) - now).total_seconds()
        await asyncio.sleep(max(1.0, delay))
        try:
            await asyncio.to_thread(run_pull_once, app.state.data_dir,
                                    app.state.config_path, ttl_minutes=ttl)
        except Exception:  # noqa: BLE001 - 定时任务异常不能杀死循环
            logger.exception("定时拉数执行失败")


def status(data_dir) -> dict:
    """/api/schedule/status 数据源：开关 / cron / 下次触发 / 分布式锁 / 最近执行。"""
    from ..data.mysql_store import default_store

    hour, minute, ttl = _cron_from_env()
    st = DistributedLock(default_store(data_dir), LOCK_NAME, ttl_minutes=ttl).state()
    return {
        "enabled": schedule_enabled(),
        "cron": f"{hour:02d}:{minute:02d}",
        "next_run": next_run_at(_now_cn(), hour, minute).isoformat(timespec="seconds"),
        "lock": _lock_dict(st),
        "last_run": dict(last_run),
    }
