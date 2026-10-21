"""invest Web 管理平台（本地单用户）。

create_app() 工厂：路径可注入（测试用 tmp 目录）、Host 白名单可配置。
分层铁律：webapp 内只调 reporting/领域层，禁止直接 import pandas/metrics/ledger 做计算。
路由一律同步 def（pandas 计算由 FastAPI 丢线程池，避免卡事件循环）。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import config as cfg
from .security import CacheHeadersMiddleware, HostCheckMiddleware, TokenAuthMiddleware

DEFAULT_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]", "host.docker.internal"}

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _fmt(value, digits: int = 2) -> str:
    """千分位格式化；None → 占位符。"""
    if value is None:
        return "—"
    return f"{value:,.{digits}f}"


def _pct(value, digits: int = 2) -> str:
    """小数 → 百分比字符串。"""
    if value is None:
        return "—"
    return f"{value * 100:.{digits}f}%"


templates.env.filters["fmt"] = _fmt
templates.env.filters["pct"] = _pct

# 静态资源内容指纹：文件一变 URL 就变（?v=<md5前8位>）。
# 动机：本机系统代理会缓存静态资源，恒定版本号(v=dev)导致浏览器长期拿到旧CSS——
# 内容指纹让任何缓存层(浏览器/代理)都不可能再喂过期文件。
import hashlib

_ASSET_FINGERPRINT: dict[str, tuple[float, str]] = {}


def _asset(path: str) -> str:
    full = BASE_DIR / "static" / path
    key = str(full)
    try:
        mtime = full.stat().st_mtime
        cached = _ASSET_FINGERPRINT.get(key)
        if not cached or cached[0] != mtime:
            digest = hashlib.md5(full.read_bytes()).hexdigest()[:8]
            _ASSET_FINGERPRINT[key] = (mtime, digest)
        v = _ASSET_FINGERPRINT[key][1]
    except OSError:
        v = "missing"
    return f"/static/{path}?v={v}"


templates.env.filters["asset"] = _asset


def create_app(
    allowed_hosts: set[str] | None = None,
    config_path: Path | None = None,
    data_dir: Path | None = None,
    mp_token: str | None = None,
    auth_mode: str | None = None,
) -> FastAPI:
    app = FastAPI(title="invest · 个人投资管理平台", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.allowed_hosts = allowed_hosts if allowed_hosts is not None else set(DEFAULT_HOSTS)
    app.state.config_path = config_path  # None → load_config 默认(local.yaml优先)
    app.state.data_dir = data_dir if data_dir is not None else cfg.DATA_DIR
    # 鉴权模式：token=LAN静态令牌 | star=star平台JWT（网关后纵深防御）；None=本机模式不鉴权
    app.state.auth_mode = auth_mode or ("token" if mp_token else None)
    app.state.mp_token = mp_token or None
    app.state.app_version = cfg.__version__ if hasattr(cfg, "__version__") else "dev"

    app.add_middleware(CacheHeadersMiddleware)
    app.add_middleware(HostCheckMiddleware)
    app.add_middleware(TokenAuthMiddleware)

    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    from . import routes_api, routes_mp, routes_pages

    app.include_router(routes_pages.router)
    app.include_router(routes_api.router)
    app.include_router(routes_mp.router)
    return app
