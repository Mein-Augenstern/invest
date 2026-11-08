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


def glm_key_file(data_dir) -> Path:
    """GLM key 持久化文件路径（gitignored，不入库）。

    优先 INVEST_GLM_KEY_FILE（容器部署：config 目录只读挂载时指到可写的数据卷，
    如 /data/glm.local.env）；缺省沿用本机布局 <data_dir>/../config/glm.local.env。
    """
    import os

    override = os.environ.get("INVEST_GLM_KEY_FILE")
    if override:
        return Path(override)
    return Path(data_dir).parent / "config" / "glm.local.env"


def load_glm_key_from_file(data_dir) -> None:
    """启动时把 key 文件载入 os.environ（容器重启后 AI 解读仍可用，免手动注入）。

    已设置 INVEST_GLM_API_KEY 时不覆盖（显式 env 优先）。
    """
    import os

    if os.environ.get("INVEST_GLM_API_KEY"):
        return
    f = glm_key_file(data_dir)
    if f.exists():
        value = f.read_text(encoding="utf-8").strip()
        for line in value.splitlines():
            if line.startswith("INVEST_GLM_API_KEY="):
                os.environ["INVEST_GLM_API_KEY"] = line.split("=", 1)[1].strip()
                return
