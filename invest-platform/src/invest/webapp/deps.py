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
    """会员视角组合：yaml 种子 + 该会员的 db 标的（S11 隔离）。"""
    return load_portfolio(get_store(request), request.app.state.config_path, get_member_id(request))


def get_data_dir(request: Request) -> Path:
    return Path(request.app.state.data_dir)


def get_trades_path(request: Request) -> Path:
    return Path(request.app.state.data_dir) / "trades.csv"


def get_member_id(request: Request) -> int:
    """当前会员 id：star JWT 的 sub；token/本机模式回落默认会员
    （INVEST_DEFAULT_MEMBER_ID，生产指向运营者）。"""
    mid = getattr(request.state, "member_id", None)
    if isinstance(mid, int):
        return mid
    from ..data.local import default_member_id

    return default_member_id()


def get_trades(request: Request) -> list:
    """当前会员的流水（S11：store 化，CSV 仅为导出格式）。"""
    from ..ledger.trades import Trade

    rows = get_store(request).list_trades(get_member_id(request))
    return [
        Trade(
            date=r["date"],
            instrument_id=r["instrument_id"],
            action=r["action"],
            quantity=float(r["quantity"]),
            price=float(r["price"]),
            fee=float(r.get("fee") or 0),
            note=r.get("note") or "",
        )
        for r in rows
    ]


def require_admin(request: Request) -> int:
    """运营者守卫：ADMIN_MEMBER_IDS（逗号分隔）内的会员放行，其余 403。"""
    import os

    member_id = get_member_id(request)
    admins = {int(x) for x in os.environ.get("INVEST_ADMIN_MEMBER_IDS", "").split(",") if x.strip().isdigit()}
    if member_id not in admins:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail={"error": "需要运营者权限"})
    return member_id


def audit(request: Request, action: str, detail: str = "") -> None:
    """写操作审计（S11 AC-6）：who/what/when/traceId，不含金额明文。"""
    get_store(request).add_audit(
        get_member_id(request), action, detail,
        getattr(request.state, "trace_id", "") or "",
    )


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
