"""S05 外部 API 韧性：超时 → 缓存降级 → 多源兜底。

分层防护（与 akshare_provider 配合）：
- 第 1 层（akshare_provider._with_timeout）：单次 akshare 调用 10s 超时，超时返回 None；
- 第 2 层（本模块 ResilientProvider）：primary 失败 → 本地缓存 → fallback 数据源；
- 第 3 层（webapp 路由）：降级路径返回的数据打 stale=True 标记，前端明示"非最新"。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# 超过 6 小时未刷新的缓存视为 stale（降级数据，可展示但需标记）
STALE_THRESHOLD = timedelta(hours=6)


def is_stale(updated_at: str | datetime | None, now: datetime | None = None) -> bool:
    """判断缓存时间戳是否超过 STALE_THRESHOLD。

    updated_at 缺失/无法解析时按 stale 处理（宁可误标，不可漏标）。
    """
    if not updated_at:
        return True
    ts = updated_at if isinstance(updated_at, datetime) else _parse(updated_at)
    if ts is None:
        return True
    return (now or datetime.now()) - ts > STALE_THRESHOLD


def _parse(ts: str) -> datetime | None:
    """解析存储层的时间戳（ISO 格式，本地无时区）；失败返回 None。"""
    try:
        return datetime.fromisoformat(str(ts).strip())
    except ValueError:
        return None


class ResilientProvider:
    """包装任意 DataProvider，增加超时/缓存/降级三重防护。

    - primary: 主数据源（如 AkshareProvider），需提供 fetch_series(instrument_id, kind, **kwargs)；
    - cache:   本地缓存读取方（如 LocalStore 适配器），primary 失败时先查缓存；
    - fallback: 备用数据源，缓存也没有时最后尝试。

    三者都失败时返回 None（不抛异常），由调用方决定空态展示。
    """

    def __init__(self, primary: object, fallback: object = None, cache: object = None):
        self.primary = primary
        self.fallback = fallback
        self.cache = cache

    def fetch_series(self, instrument_id: str, kind: str, **kwargs) -> dict | None:
        """优先 primary → 超时/失败后查缓存 → fallback → 全部失败返回 None。

        返回 dict（含 stale 标记）：主源命中 stale=False；缓存/兜底命中
        stale=True 且 source 注明来源；全部失败返回 None。
        """
        # 1) 主数据源
        result = self._try(self.primary, instrument_id, kind, **kwargs)
        if result:
            return {**result, "stale": False}

        # 2) primary 失败 → 本地缓存（旧数据可用总比没数据强，但必须打 stale 标）
        if self.cache is not None:
            result = self._try(self.cache, instrument_id, kind, **kwargs)
            if result:
                logger.warning("[S05降级] %s/%s 走本地缓存", instrument_id, kind)
                return {**result, "stale": True, "source": "cache"}

        # 3) 缓存也没有 → fallback 备用源
        if self.fallback is not None:
            result = self._try(self.fallback, instrument_id, kind, **kwargs)
            if result:
                logger.warning("[S05降级] %s/%s 走备用源", instrument_id, kind)
                return {**result, "stale": True, "source": "fallback"}

        logger.warning("[S05降级] %s/%s 主源/缓存/备用源全部失败", instrument_id, kind)
        return None

    def _try(self, provider: object, *args, **kwargs) -> dict | None:
        """单源尝试：任何异常吞掉记日志，返回 None 交由上层继续降级。"""
        try:
            return provider.fetch_series(*args, **kwargs)  # type: ignore[attr-defined]
        except Exception as e:  # noqa: BLE001 - 降级链路里单源失败不算错误
            logger.warning("Provider %s 失败: %s", type(provider).__name__, e)
            return None

    def __getattr__(self, name: str):
        """DataProvider 协议方法（etf_daily/fund_nav 等）透明转发给 primary。

        超时防护已在 AkshareProvider 内部逐调用实现，这里只做转发，
        保持 ResilientProvider 可直接替换 run_pull 中的 provider 参数。
        """
        primary = self.__dict__.get("primary")  # 不走 self.primary，防拷贝/反序列化期递归
        if primary is None:
            raise AttributeError(name)
        return getattr(primary, name)
