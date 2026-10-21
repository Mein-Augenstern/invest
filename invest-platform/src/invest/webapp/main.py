"""uvicorn 入口：invest.webapp.main:app（import string 形式，--reload 才生效）。

鉴权与 Host 经环境变量传入（cli serve 负责注入，子进程继承环境）：
- INVEST_AUTH_MODE：token（LAN 静态令牌，配 INVEST_MP_TOKEN）| star（star 平台 JWT）
- INVEST_JWT_SECRET：star 模式密钥（默认与 star dev 值一致）
- INVEST_MP_TOKEN：token 模式令牌
- INVEST_HOSTS_EXTRA：逗号分隔的额外放行 Host（LAN IP）
"""
import os

from . import create_app

_extra = {h.strip() for h in os.environ.get("INVEST_HOSTS_EXTRA", "").split(",") if h.strip()}
_hosts = None if not _extra else {"127.0.0.1", "localhost", "::1", "[::1]"} | _extra

app = create_app(
    auth_mode=os.environ.get("INVEST_AUTH_MODE") or None,
    mp_token=os.environ.get("INVEST_MP_TOKEN") or None,
    allowed_hosts=_hosts,
)
