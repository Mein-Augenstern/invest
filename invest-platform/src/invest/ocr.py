"""图片识别录入（S1）：券商/基金 App 截图 → 本地 OCR → LLM 结构化为流水草稿。

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
    api_key = os.environ.get("INVEST_GLM_API_KEY")
    if not api_key or not ocr_text.strip():
        return None
    import requests

    base = os.environ.get("INVEST_GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/chat/completions")
    model = os.environ.get("INVEST_GLM_MODEL", "glm-5.3")
    ins_desc = "\n".join(f"- {i['id']}: {i['name']} ({i['type']})" for i in instruments)
    try:
        resp = requests.post(
            base,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"标的清单：\n{ins_desc}\n\nOCR 文本：\n{ocr_text}"},
                ],
                "temperature": 0.1,
            },
            timeout=60,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        # 剥掉可能的 ```json 围栏
        m = re.search(r"\[.*\]", content, re.S)
        if not m:
            return None
        rows = json.loads(m.group(0))
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
    except Exception:  # noqa: BLE001 - 降级不阻断
        return None
