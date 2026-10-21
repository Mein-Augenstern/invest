"""GLM 智能层：基于本地报告数据生成解读。

边界（章程红线4）：LLM 只做信息压缩与逻辑推理，不做涨跌预测；
解读必须引用报告中的具体数字；策略执行以规则书信号为准。
"""
from __future__ import annotations

import os

SYSTEM_PROMPT = """你是个人投研平台的解读助手。严格遵守：
1. 只基于用户提供的报告数据做解读，不得引入外部数据或猜测；
2. 禁止预测涨跌、禁止给出买卖时点建议；策略执行以规则书信号为准；
3. 中文输出，分三节：估值解读 / 组合解读 / 纪律提示；
4. 总长300字以内，所有结论引用报告中的具体数字。"""

FALLBACK_HINT = (
    "（未配置 INVEST_GLM_API_KEY，跳过 AI 解读。\n"
    "启用方法: export INVEST_GLM_API_KEY=<智谱API Key> 后运行 invest report --ai）"
)


def generate_digest(report_md: str) -> str:
    """有 key 调用智谱 GLM 生成解读；无 key 返回降级提示（不抛错）。"""
    api_key = os.environ.get("INVEST_GLM_API_KEY")
    if not api_key:
        return FALLBACK_HINT
    import requests  # 局部导入：无AI需求的环境不强依赖网络调用

    base = os.environ.get("INVEST_GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/chat/completions")
    model = os.environ.get("INVEST_GLM_MODEL", "glm-5.3")
    try:
        resp = requests.post(
            base,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": report_md},
                ],
                "temperature": 0.3,
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:  # noqa: BLE001 - 降级不阻断报告生成
        return f"（AI 解读调用失败: {type(e).__name__}: {e}）"
