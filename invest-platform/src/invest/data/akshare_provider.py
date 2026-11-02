"""akshare 数据源实现。

所有 akshare 调用集中在本文件（接口常变，坏了好修）。
口径登记见 docs/03-data-sources.md。2026-09-05 实测结论：
- 东财 push2his 子域本机 SSL 失败 → ETF行情用新浪兜底（不复权口径）
- 乐咕不覆盖新中证指数代码 → 指数估值改用中证官网（官方，仅近20日，需每日沉淀）
"""
from __future__ import annotations

import concurrent.futures
import logging
from datetime import datetime

import akshare as ak
import pandas as pd

from .provider import IndexValuation, normalize

logger = logging.getLogger(__name__)

# S05 外部 API 韧性：单次 akshare 调用的默认超时（秒）。
# akshare 内部 requests 多数未设 timeout，网络抖动时会无限挂死拉数线程——
# 这里在调用方统一加线程级超时保护。
FALLBACK_TIMEOUT = 10
# 全量历史/全目录类接口（无起止日期参数，一次拉十几年数据）给 3 倍余量。
BULK_TIMEOUT = FALLBACK_TIMEOUT * 3


def _with_timeout(func, *args, timeout: float = FALLBACK_TIMEOUT, **kwargs):
    """用线程池包裹 akshare 调用，超时返回 None（不阻塞主线程）。

    注意：不能用 `with ThreadPoolExecutor(...) as pool` 写法——退出 with 会
    shutdown(wait=True) 等工作线程跑完，挂死的调用仍会拖住主线程；这里显式
    shutdown(wait=False)，超时后立即返回，残留线程随进程存续。
    """
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            logger.warning("akshare 调用超时(%ss): %s", timeout, getattr(func, "__name__", func))
            return None
        except Exception as e:  # noqa: BLE001 - 调用失败降级为 None，由上层兜底
            logger.warning("akshare 调用失败: %s: %s", getattr(func, "__name__", func), e)
            return None
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _sina_symbol(etf_code: str) -> str:
    """新浪ETF代码带市场前缀：5开头=沪，其余=深。"""
    return ("sh" if etf_code.startswith("5") else "sz") + etf_code


def _stock_symbol(code: str) -> str:
    """个股代码带市场前缀（新浪/腾讯口径）：6开头=沪，0/3开头=深。"""
    return ("sh" if code.startswith("6") else "sz") + code


class AkshareProvider:
    name = "akshare"

    def etf_daily(self, code: str, start: str = "2015-01-01") -> pd.DataFrame:
        try:
            raw = _with_timeout(
                ak.fund_etf_hist_em,
                symbol=code,
                period="daily",
                start_date=start.replace("-", ""),
                end_date=datetime.now().strftime("%Y%m%d"),
                adjust="qfq",  # 前复权：分红除权不造成价格跳水
            )
            if raw is None:  # 超时/失败 → 抛错走新浪兜底
                raise RuntimeError(f"东财ETF行情拉取失败: {code}")
            return normalize(raw, "日期", "收盘")
        except Exception:
            # 兜底：新浪（不复权，发生份额折算的ETF历史价不可直接算收益，账本以流水为准）
            raw = _with_timeout(ak.fund_etf_hist_sina, symbol=_sina_symbol(code), timeout=BULK_TIMEOUT)
            if raw is None:
                raise RuntimeError(f"新浪ETF行情兜底也失败: {code}") from None
            df = normalize(raw, "date", "close")
            return df[df["date"] >= start].reset_index(drop=True)

    def fund_nav(self, code: str, start: str = "2015-01-01") -> pd.DataFrame:
        raw = _with_timeout(ak.fund_open_fund_info_em, symbol=code, indicator="单位净值走势", timeout=BULK_TIMEOUT)
        if raw is None:
            raise RuntimeError(f"基金单位净值拉取失败: {code}")
        df = normalize(raw, "净值日期", "单位净值")
        return df[df["date"] >= start].reset_index(drop=True)

    def stock_daily(self, code: str, start: str = "2015-01-01") -> pd.DataFrame:
        """A股个股日行情。四级兜底：东财qfq → 腾讯qfq → 新浪qfq → 新浪不复权；整体重试一轮。

        口径登记（docs/03，2026-10-18 实测）：
        - 东财 push2his 对个股接口间歇 RemoteDisconnected（风控断连，与 ETF 的 SSL 失败同源不同症）；
        - 腾讯源稳定，收盘价与东财对平（600519 1329.0 一致）；
        - 新浪接口间歇抖动，且不复权模式被限流时返回空表（rows=0 无列）——空结果视为失败逐级下探；
        - 不复权口径下分红除权日价格会跳水，账本以流水为准。
        """
        import time

        end = datetime.now().strftime("%Y%m%d")
        s, e = start.replace("-", ""), end

        def _ok(df: pd.DataFrame) -> pd.DataFrame | None:
            return None if df is None or df.empty else df

        def _once() -> pd.DataFrame:
            df = None
            try:
                raw = _with_timeout(
                    ak.stock_zh_a_hist, symbol=code, period="daily", start_date=s, end_date=e, adjust="qfq")
                df = _ok(normalize(raw, "日期", "收盘")) if raw is not None else None
            except Exception:  # noqa: BLE001 - 逐级兜底
                pass
            if df is not None:
                return df
            try:
                raw = _with_timeout(
                    ak.stock_zh_a_hist_tx, symbol=_stock_symbol(code), start_date=s, end_date=e, adjust="qfq")
                df = _ok(normalize(raw, "date", "close")) if raw is not None else None
            except Exception:  # noqa: BLE001
                pass
            if df is not None:
                return df
            for adjust in ("qfq", ""):
                try:
                    raw = _with_timeout(
                        ak.stock_zh_a_daily, symbol=_stock_symbol(code), adjust=adjust or None, timeout=BULK_TIMEOUT)
                    df = _ok(normalize(raw, "date", "close")) if raw is not None else None
                    if df is not None:
                        return df[df["date"] >= start].reset_index(drop=True)
                except Exception:  # noqa: BLE001
                    continue
            raise RuntimeError(f"个股行情四级数据源均失败: {code}")

        try:
            return _once()
        except RuntimeError:
            time.sleep(2)
            return _once()

    def bond_daily(self, code: str, start: str = "2015-01-01") -> pd.DataFrame:
        """场内债券日行情（国债/公司债/可转债），口径=收盘价。

        akshare 1.18.94 实测（2026-10-18，docs/03 登记）：
        - bond_zh_hs_hist（东财）本版本不存在，保留 hasattr 探测以为升级预留；
        - 新浪系 bond_zh_hs_daily / bond_zh_hs_cov_daily 只收 symbol、返回全量，代码内按 start 过滤；
        - 可转债用 cov 源，其余交易所债用 hs 源；两源互为兜底。
        """
        attempts: list[tuple[str, str, str, bool]] = [
            # (函数名, date列, close列, 是否传起止日期)
            ("bond_zh_hs_hist", "日期", "收盘", True),          # 东财（版本具备时优先）
            ("bond_zh_hs_daily", "date", "close", False),       # 新浪·交易所债券
            ("bond_zh_hs_cov_daily", "date", "close", False),   # 新浪·可转债
        ]
        last_err: Exception | None = None
        for fn, date_col, close_col, dated in attempts:
            func = getattr(ak, fn, None)
            if func is None:
                continue
            try:
                if dated:
                    raw = _with_timeout(
                        func, symbol=code, start_date=start.replace("-", ""),
                        end_date=datetime.now().strftime("%Y%m%d"))
                else:
                    raw = _with_timeout(func, symbol=code, timeout=BULK_TIMEOUT)
                if raw is None:  # 超时/失败 → 本源失败，继续下探下一源
                    raise RuntimeError(f"债券源 {fn} 拉取失败: {code}")
                df = normalize(raw, date_col, close_col)
                return df[df["date"] >= start].reset_index(drop=True)
            except Exception as e:  # noqa: BLE001 - 多源兜底，逐一尝试
                last_err = e
        raise RuntimeError(f"债券行情全部数据源失败: {last_err}")

    def fund_nav_cumulative(self, code: str, start: str = "2015-01-01") -> pd.DataFrame:
        """累计净值（单位净值+历次分红加回）——测真实跟踪差用，避免分红跳水低估。"""
        raw = _with_timeout(ak.fund_open_fund_info_em, symbol=code, indicator="累计净值走势", timeout=BULK_TIMEOUT)
        if raw is None:
            raise RuntimeError(f"基金累计净值拉取失败: {code}")
        df = normalize(raw, "净值日期", "累计净值")
        return df[df["date"] >= start].reset_index(drop=True)

    def refresh_catalog(self) -> pd.DataFrame:
        raw = _with_timeout(ak.index_csindex_all, timeout=BULK_TIMEOUT)
        if raw is None:
            raise RuntimeError("中证指数目录拉取失败")
        out = raw[["指数代码", "指数简称", "指数全称"]].copy()
        out.columns = ["index_code", "name", "full_name"]
        return out

    def index_valuation(self, index_code: str) -> IndexValuation:
        raw = _with_timeout(ak.stock_zh_index_value_csindex, symbol=index_code)
        if raw is None:
            raise RuntimeError(f"中证官网估值拉取失败: {index_code}")
        mapping = {
            "pe_static": "市盈率1",  # 口径定义待P2对照中证官网说明核实登记
            "pe_ttm": "市盈率2",
            "dyield_1y": "股息率1",
            "dyield_3y": "股息率2",
        }
        val = IndexValuation()
        for key, col in mapping.items():
            if col in raw.columns:
                val[key] = normalize(raw, "日期", col)
        return val

    def index_price_pe(self, index_code: str, start: str = "20130101") -> dict[str, pd.DataFrame]:
        """中证官网指数长历史：收盘点位 + 滚动市盈率（PE口径与 value 接口不同，见 docs/03）。"""
        end = datetime.now().strftime("%Y%m%d")
        raw = _with_timeout(
            ak.stock_zh_index_hist_csindex, symbol=index_code,
            start_date=start.replace("-", ""), end_date=end, timeout=BULK_TIMEOUT)
        if raw is None:
            raise RuntimeError(f"中证官网指数长历史拉取失败: {index_code}")
        out: dict[str, pd.DataFrame] = {"index_close": normalize(raw, "日期", "收盘")}
        pe = normalize(raw.assign(**{"滚动市盈率": pd.to_numeric(raw["滚动市盈率"], errors="coerce")}), "日期", "滚动市盈率")
        out["pe_ttm_hist"] = pe[pe["close"].notna()].reset_index(drop=True)
        return out

    def fund_holdings(self, code: str, year: str) -> dict:
        """基金季报前十大重仓股。返回 {period: [(rank, 股票代码, 股票名称, 占净值比例)]}。
        口径：占净值比例为小数(0.01=1%)；联接基金主要资产投向目标ETF，此为直接持股部分。"""
        raw = _with_timeout(ak.fund_portfolio_hold_em, symbol=code, date=year)
        if raw is None:
            raise RuntimeError(f"基金重仓股拉取失败: {code}")
        out: dict[str, list[tuple]] = {}
        for r in raw.itertuples():
            period = getattr(r, "季度", "")
            out.setdefault(period, []).append(
                (int(r.序号), str(r.股票代码), str(r.股票名称), float(r.占净值比例))
            )
        return out

    def fund_industry(self, code: str, year: str) -> tuple[str, list[tuple]]:
        """基金行业配置。返回 (报告日, [(行业, 占净值比例)])。"""
        raw = _with_timeout(ak.fund_portfolio_industry_allocation_em, symbol=code, date=year)
        if raw is None:
            raise RuntimeError(f"基金行业配置拉取失败: {code}")
        rows = [
            (str(r.行业类别), float(r.占净值比例))
            for r in raw.itertuples()
        ]
        dates = sorted(raw["截止时间"].astype(str).unique())
        return (dates[-1] if dates else "", rows)

    def bond_yield_10y(self, start: str = "2013-01-01") -> pd.DataFrame:
        """中国10年期国债收益率(%)日序列。口径：收益率单位为百分数(1.69=1.69%)。"""
        raw = _with_timeout(ak.bond_zh_us_rate, start_date=start.replace("-", "")[:8], timeout=BULK_TIMEOUT)
        if raw is None:
            raise RuntimeError("中美国债收益率拉取失败")
        raw = raw.rename(columns={"日期": "date", "中国国债收益率10年": "yield"})
        df = raw[["date", "yield"]].copy()
        df["date"] = df["date"].astype(str)
        df["yield"] = pd.to_numeric(df["yield"], errors="coerce")
        df = df.dropna().drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
        df.columns = ["date", "close"]  # 复用 series 表结构
        return df[df["date"] >= start].reset_index(drop=True)
