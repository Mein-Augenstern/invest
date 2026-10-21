"""图片识别录入（S1）：券商/基金 App 截图 → 本地 OCR → LLM 结构化为流水草稿。
标的详情页截图 → 同链路结构化为新标的草稿（S2 标的识别录入）。

成本模型（参照语音工程双轨）：
- OCR：macOS Vision 本地识别（免费、离线、中文强），图片即用即删不落数据目录；
- 结构化：GLM 文本解析（token 极廉价）；无 INVEST_GLM_API_KEY 时优雅降级——
  返回 OCR 原文由用户在预览中手动整理，识别能力不受影响只少了自动填表。

安全：仅临时目录处理；大小/扩展名白名单在端点层校验。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .config import INSTRUMENT_TYPES

SYSTEM_PROMPT = """你是投资账本的结构化助手。输入是一张券商/基金/银行 App 截图的 OCR 文本，
以及账本现有的标的清单。请提取其中的交易/持仓信息，输出严格的 JSON 数组（不要任何其他文字）：
[{"date":"YYYY-MM-DD","action":"buy|sell|contribute|dividend_cash|dividend_reinvest",
   "instrument_id":"从标的清单选最匹配的 id，无法匹配填空串","quantity":数字,"price":数字,
   "fee":数字或0,"note":"简短备注"}]
规则：
- 申购/买入=buy，赎回/卖出=sell，缴存/入金=contribute，现金分红=dividend_cash，红利再投=dividend_reinvest；
- 金额与份额都给时：quantity=份额 price=净值；只有金额时 quantity=金额 price=1 note 注明"按金额"；
- 持仓快照（非交易）只提取当前份额与最新净值：action=adjust，note 注明"持仓快照"；
- OCR 里没有的信息不要编造；识别不出的行直接跳过。"""

INSTRUMENT_PROMPT = """你是投资账本的结构化助手。输入是一张基金/券商/银行 App 的标的详情页
（或搜索结果、产品介绍页）截图的 OCR 文本，以及账本已有的标的 id 清单。
请提取其中"新增标的"所需的字段，输出严格的 JSON 对象（不要任何其他文字）：
{"name":"展示名称","type":"etf|open_end_fund|stock|bond|wealth 之一","code":"交易/基金代码",
 "benchmark_index":"跟踪指数或业绩比较基准","account":"账户 slug","id":"建议的标识 slug"}
规则：
- type 判定：场内 ETF/LOF=etf，场外开放基金（含 ETF 联接、指数基金申购）=open_end_fund，
  个股=stock，国债/可转债/债券=bond（代码需带 sh/sz 前缀），银行理财/存款/固收=wealth；
- name 去掉销售机构前缀，保留可辨识的产品名（如"易方达沪深300ETF联接A"）；
- code：截图里的基金/证券代码；理财类无代码填空串；债券若 OCR 无市场前缀，沪市补 sh 深市补 sz；
- benchmark_index：跟踪指数（如 中证红利/沪深300）；看不出来填空串；
- account：从文字里能明确判断时给小写 slug（如 个人养老金→pension、A股→a_stock、银行→bank），否则填空串；
- id：2-32 位小写字母/数字/下划线的唯一 slug（常见做法：场外基金 f+代码、ETF e+代码、股票 s+代码、
  债券 b+去前缀代码），拿不到可靠代码时给名字的合理音译 slug；不得与已有 id 清单重复；
- OCR 里没有的信息一律填空串，不要编造。"""


def _glm_chat(system: str, user: str) -> str | None:
    """GLM 文本结构化公共通道：无 Key 或任何失败返回 None（端点降级为手动整理）。"""
    api_key = os.environ.get("INVEST_GLM_API_KEY")
    if not api_key:
        return None
    import requests

    base = os.environ.get("INVEST_GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/chat/completions")
    model = os.environ.get("INVEST_GLM_MODEL", "glm-5.3")
    try:
        resp = requests.post(
            base,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.1,
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:  # noqa: BLE001 - 降级不阻断
        return None


def ocr_image(path: Path) -> str:
    """macOS Vision 本地 OCR（zh-Hans + en-US，精确模式）。"""
    import Vision
    from Foundation import NSURL

    url = NSURL.fileURLWithPath_(str(path))
    handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, None)
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLanguages_(["zh-Hans", "en-US"])
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    ok, err = handler.performRequests_error_([request], None)
    if not ok:
        raise RuntimeError(f"Vision OCR 失败: {err}")
    lines: list[str] = []
    for obs in request.results() or []:
        top = obs.topCandidates_(1)
        if top:
            lines.append(str(top[0].string()))
    return "\n".join(lines)


def parse_trades_by_llm(ocr_text: str, instruments: list[dict]) -> list[dict] | None:
    """GLM 把 OCR 文本结构化为流水草稿；无 Key 或失败返回 None（降级手动）。"""
    if not ocr_text.strip():
        return None
    ins_desc = "\n".join(f"- {i['id']}: {i['name']} ({i['type']})" for i in instruments)
    content = _glm_chat(SYSTEM_PROMPT, f"标的清单：\n{ins_desc}\n\nOCR 文本：\n{ocr_text}")
    if not content:
        return None
    # 剥掉可能的 ```json 围栏
    m = re.search(r"\[.*\]", content, re.S)
    if not m:
        return None
    try:
        rows = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(rows, list):
        return None
    # 轻量清洗：数字字段容错
    for r in rows:
        for k in ("quantity", "price", "fee"):
            try:
                r[k] = float(str(r.get(k, 0)).replace(",", ""))
            except (TypeError, ValueError):
                r[k] = 0.0
    return rows


def parse_instrument_by_llm(ocr_text: str, existing_ids: list[str]) -> dict | None:
    """GLM 把标的详情页 OCR 文本结构化为新标的草稿；无 Key 或失败返回 None（降级手动）。

    返回字段与 POST /api/instruments 载荷对齐（id/name/type/code/benchmark_index/account），
    全部字符串化并做 enum/前缀级清洗，空值一律空串。"""
    if not ocr_text.strip():
        return None
    content = _glm_chat(
        INSTRUMENT_PROMPT,
        f"已有标的 id 清单：\n{', '.join(existing_ids) or '（空）'}\n\nOCR 文本：\n{ocr_text}",
    )
    if not content:
        return None
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        return None
    try:
        row = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(row, dict):
        return None
    out = {k: str(row.get(k) or "").strip() for k in
           ("id", "name", "type", "code", "benchmark_index", "account")}
    if out["type"] not in INSTRUMENT_TYPES:
        out["type"] = ""  # 模型输出跑偏时不落非法值，交用户在表单里选
    if out["id"] and (not re.match(r"^[a-z0-9_]{2,32}$", out["id"]) or out["id"] in existing_ids):
        out["id"] = ""
    return out
