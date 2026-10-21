"""安全与缓存中间件。

- HostCheckMiddleware：仅放行白名单 Host（防 DNS 重绑定）；测试可注入 testserver。
- TokenAuthMiddleware：双鉴权模式（app.state.auth_mode）
  · token（默认）：LAN 模式静态令牌，app.state.mp_token 非空即启用；
  · star：校验 star 平台 JWT（网关 JwtGlobalFilter 同款——HS256 共享密钥、subject=memberId），
    invest 作为独立微服务挂在 star 网关后的纵深防御层。
  两模式共用 ping 白名单；本机模式（两者都未配置）不鉴权。
- CacheHeadersMiddleware：vendor 静态资源长缓存 immutable；其余静态 no-cache；
  HTML/接口一律 no-store（持仓金额不进浏览器磁盘缓存——敏感数据不出本机的延伸）。
"""
from __future__ import annotations

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# 无需鉴权即可访问的路径（连通性探测）
TOKEN_EXEMPT = {"/api/ping", "/api/invest/ping"}

# 无内置默认密钥（public 仓红线）：star 模式必须经 INVEST_JWT_SECRET 注入，
# 与 star 平台各服务的 jwt.secret 保持一致（历史 dev 默认值已于 public 化时移除）


def _star_jwt_secret() -> str:
    return os.environ.get("INVEST_JWT_SECRET") or ""


def parse_star_member(jwt_lib, token: str, secret: str) -> int | None:
    """校验 star JWT，返回 memberId（subject）；非法/过期返回 None。jwt_lib 作参数便于测试注入。"""
    try:
        claims = jwt_lib.decode(token, secret, algorithms=["HS256"])
    except Exception:  # noqa: BLE001 - 任何解析失败都视为未登录
        return None
    try:
        return int(claims.get("sub"))
    except (TypeError, ValueError):
        return None


class HostCheckMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        allowed: set[str] = request.app.state.allowed_hosts
        host = (request.headers.get("host") or "").split(":")[0]
        if host not in allowed:
            return JSONResponse({"error": "host not allowed"}, status_code=403)
        return await call_next(request)


class TokenAuthMiddleware(BaseHTTPMiddleware):
    """鉴权：Authorization: Bearer <token|jwt> 或 ?token=<token>（后者方便浏览器调试）。"""

    async def dispatch(self, request: Request, call_next):
        mode = getattr(request.app.state, "auth_mode", None)
        if mode not in ("token", "star") or request.url.path in TOKEN_EXEMPT:
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        supplied = auth.removeprefix("Bearer ").strip() or request.query_params.get("token", "")
        if not supplied:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if mode == "token":
            if supplied == getattr(request.app.state, "mp_token", None):
                return await call_next(request)
        else:  # star
            import jwt as pyjwt

            if parse_star_member(pyjwt, supplied, _star_jwt_secret()) is not None:
                return await call_next(request)
        return JSONResponse({"error": "unauthorized"}, status_code=401)


class CacheHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/static/vendor/"):
            response.headers["Cache-Control"] = "public, max-age=604800, immutable"
        elif path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        else:
            response.headers["Cache-Control"] = "no-store"
        return response
