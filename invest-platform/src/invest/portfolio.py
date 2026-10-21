"""组合装配（S2）：yaml 种子 + SQLite 运行时标的合并。

- yaml（portfolio.local.yaml）仍是种子与权威示例；小程序端新增/编辑的标的落 instruments 表；
- 合并规则：db 中同 id 覆盖 yaml 定义（可改名称/代码/账户），db 新增的追加；
- 侵入面控制：不改 config.load_config，由调用方（webapp deps / CLI）显式 merge。
"""
from __future__ import annotations

from . import config as cfg
from .config import Account, Instrument, Portfolio
from .data.local import LocalStore


def load_portfolio(store: LocalStore | None = None, config_path=None) -> Portfolio:
    """load_config + 可选的 db 标的合并。store 传 None 退化为纯 yaml（测试兼容）。"""
    conf = cfg.load_config(config_path)
    if store is None:
        return conf
    db_rows = store.list_instruments()
    if not db_rows:
        return conf
    by_id = {i.id: i for i in conf.instruments}
    for r in db_rows:
        ins = Instrument(
            id=r[0], type=r[1], name=r[2], code=r[3] or "",
            benchmark_index=r[4] or "", benchmark_tr_code=r[5] or "",
            account=r[6] or "",
        )
        by_id[ins.id] = ins  # db 覆盖同 id（含 yaml 种子）
    conf.instruments = list(by_id.values())
    # db 标的引用的账户若 yaml 未定义，补一个通用账户占位（账户体系仍是 yaml 定义）
    known = set(conf.accounts)
    for ins in conf.instruments:
        if ins.account and ins.account not in known:
            conf.accounts[ins.account] = Account(id=ins.account, name=ins.account)
            known.add(ins.account)
    return conf
