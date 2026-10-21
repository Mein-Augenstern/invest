"""请求级依赖：从 app.state 取可注入路径，构造配置与存储（每次现建，配置热更新）。

S2 起 get_conf 走 load_portfolio（yaml 种子 + SQLite 运行时标的合并）——
小程序端增改标的即时生效，无需重启。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import Request

from .. import config as cfg
from ..data.mysql_store import default_store
from ..portfolio import load_portfolio


def get_store(request: Request):
    """存储工厂：INVEST_DB_URL=mysql://… 用 MySQL（star 同实例 invest 库），缺省 SQLite。"""
    return default_store(request.app.state.data_dir)


def get_conf(request: Request) -> cfg.Portfolio:
    return load_portfolio(get_store(request), request.app.state.config_path)


def get_data_dir(request: Request) -> Path:
    return Path(request.app.state.data_dir)


def get_trades_path(request: Request) -> Path:
    return Path(request.app.state.data_dir) / "trades.csv"
