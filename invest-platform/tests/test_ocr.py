"""S1 图片识别录入：Vision OCR 冒烟 + LLM 结构化 mock + 端点全链路。"""
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from invest import config as cfg
from invest.ocr import ocr_image, parse_instrument_by_llm, parse_trades_by_llm
from invest.webapp import create_app


def _cjk_font(size: int = 28):
    """系统 CJK 字体自适应（macOS 各版本预装字体不同：PingFang→Hiragino→STHeiti）。"""
    for p in (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
    ):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    raise OSError("无可用系统 CJK 字体")


def _make_shot(path: Path):
    font = _cjk_font()
    img = Image.new("RGB", (620, 280), "white")
    d = ImageDraw.Draw(img)
    d.text((30, 30), "申购买入 5,000.00 元", font=font, fill="black")
    d.text((30, 90), "确认日期 2026-10-15", font=font, fill="black")
    d.text((30, 150), "确认份额 3,862.54 份", font=font, fill="black")
    d.text((30, 210), "确认净值 1.2947", font=font, fill="black")
    img.save(path)


def test_vision_ocr_chinese(tmp_path):
    """本机 Vision OCR：中文交易要素可识别（数字与日期精确）。"""
    shot = tmp_path / "shot.png"
    _make_shot(shot)
    text = ocr_image(shot)
    assert "5,000.00" in text or "5000.00" in text
    assert "2026-10-15" in text
    assert "3,862.54" in text or "3862.54" in text
    assert "1.2947" in text


def test_llm_parse_fallback_without_key(monkeypatch):
    monkeypatch.delenv("INVEST_GLM_API_KEY", raising=False)
    assert parse_trades_by_llm("任意文本", [{"id": "a", "name": "A", "type": "etf"}]) is None


def test_llm_parse_cleans_numbers(monkeypatch):
    """GLM 返回逗号数字/围栏 JSON 时被清洗为可用的流水草稿。"""

    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "```json\n[{\"date\":\"2026-10-15\",\"action\":\"buy\",\"instrument_id\":\"a\",\"quantity\":\"3,862.54\",\"price\":\"1.2947\",\"fee\":\"0\",\"note\":\"\"}]\n```"}}]}

    monkeypatch.setenv("INVEST_GLM_API_KEY", "k")
    monkeypatch.setattr("requests.post", lambda *a, **k: FakeResp())
    rows = parse_trades_by_llm("text", [{"id": "a", "name": "A", "type": "etf"}])
    assert rows == [{"date": "2026-10-15", "action": "buy", "instrument_id": "a",
                     "quantity": 3862.54, "price": 1.2947, "fee": 0.0, "note": ""}]


@pytest.fixture()
def client(tmp_path):
    app = create_app(
        allowed_hosts={"testserver"},
        config_path=cfg.CONFIG_DIR / "portfolio.example.yaml",
        data_dir=tmp_path,
    )
    return TestClient(app)


def test_ocr_endpoint_roundtrip(client, tmp_path, monkeypatch):
    """端点全链路：上传→OCR→（无Key）降级返回文本；文件校验拒绝非图片。"""
    shot = tmp_path / "shot.png"
    _make_shot(shot)
    monkeypatch.delenv("INVEST_GLM_API_KEY", raising=False)
    r = client.post("/api/invest/ocr", files={"file": ("shot.png", shot.read_bytes(), "image/png")})
    assert r.status_code == 200
    data = r.json()
    assert data["ai_parsed"] is False and data["trades"] is None
    assert "2026-10-15" in data["text"]

    # 非图片扩展名拒绝
    r2 = client.post("/api/invest/ocr", files={"file": ("x.txt", b"abc", "text/plain")})
    assert r2.status_code == 422


# ---------- S2 标的识别录入 ----------

def _make_ins_shot(path: Path):
    font = _cjk_font()
    img = Image.new("RGB", (620, 340), "white")
    d = ImageDraw.Draw(img)
    d.text((30, 30), "易方达沪深300ETF联接A", font=font, fill="black")
    d.text((30, 90), "基金代码 110022", font=font, fill="black")
    d.text((30, 150), "跟踪指数 沪深300", font=font, fill="black")
    d.text((30, 210), "个人养老金账户", font=font, fill="black")
    d.text((30, 270), "单位净值 1.2947", font=font, fill="black")
    img.save(path)


def test_instrument_llm_fallback_without_key(monkeypatch):
    monkeypatch.delenv("INVEST_GLM_API_KEY", raising=False)
    assert parse_instrument_by_llm("任意文本", ["a"]) is None


def test_instrument_llm_parse_cleans(monkeypatch):
    """GLM 返回围栏 JSON/非法 type/撞车 id 时被清洗为可用草稿。"""

    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": (
                '```json\n{"name":"易方达沪深300ETF联接A","type":"场外基金","code":"110022",'
                '"benchmark_index":"沪深300","account":"pension","id":"a"}\n```'
            )}}]}

    monkeypatch.setenv("INVEST_GLM_API_KEY", "k")
    monkeypatch.setattr("requests.post", lambda *a, **k: FakeResp())
    from invest.ocr import parse_instrument_by_llm
    row = parse_instrument_by_llm("text", ["a", "b"])
    assert row == {"id": "", "name": "易方达沪深300ETF联接A", "type": "",
                   "code": "110022", "benchmark_index": "沪深300", "account": "pension"}


def test_instrument_parse_endpoint_roundtrip(client, tmp_path, monkeypatch):
    """标的识别端点全链路：上传→OCR→（无Key）降级只回原文；非法扩展名 422。"""
    shot = tmp_path / "ins.png"
    _make_ins_shot(shot)
    monkeypatch.delenv("INVEST_GLM_API_KEY", raising=False)
    r = client.post("/api/invest/instruments/parse-image",
                    files={"file": ("ins.png", shot.read_bytes(), "image/png")})
    assert r.status_code == 200
    data = r.json()
    assert data["ai_parsed"] is False and data["instrument"] is None
    assert "110022" in data["text"] and "沪深300" in data["text"]

    r2 = client.post("/api/invest/instruments/parse-image",
                     files={"file": ("x.txt", b"abc", "text/plain")})
    assert r2.status_code == 422
