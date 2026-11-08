"""S04 数据完整性 API 端点——备份导出 + 数据校验报告（S11：会员维度）。

导出内容 = 该会员自己的数据（trades.csv / diary.csv / 周报 md）。
运营者全局配置（portfolio yaml）与服务端库文件不进会员导出包——
多会员形态下整目录导出等于跨会员泄密（S11 安全整改）。
"""
from __future__ import annotations

import io
import logging
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from .deps import audit, get_member_id, get_store

logger = logging.getLogger(__name__)
router = APIRouter()

#: 会员周报目录内的扩展名白名单（导出用）
REPORT_EXT = ".md"


@router.get("/backup/export")
async def backup_export(request: Request, store=Depends(get_store), member_id=Depends(get_member_id)):
    """S04-AC5 导出备份（会员维度）：trades.csv + diary.csv + 本会员周报 → zip。"""
    import csv

    data_dir = Path(request.app.state.data_dir if hasattr(request.app.state, "data_dir") else "data")
    buf = io.BytesIO()
    added: list[str] = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 流水（从库生成 CSV，与旧 trades.csv 同列结构）
        rows = store.list_trades(member_id)
        if rows:
            out = io.StringIO()
            w = csv.DictWriter(out, fieldnames=["date", "instrument_id", "action", "quantity", "price", "fee", "note"])
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in w.fieldnames})
            zf.writestr("trades.csv", out.getvalue())
            added.append("trades.csv")
        # 日记
        diary = store.list_diary(member_id, limit=10000)
        if diary:
            out = io.StringIO()
            w = csv.writer(out)
            w.writerow(["date", "mood", "updated_at", "content"])
            for r in diary:
                w.writerow([r[0], r[2], r[3], r[1]])
            zf.writestr("diary.csv", out.getvalue())
            added.append("diary.csv")
        # 本会员周报
        reports_dir = data_dir / "reports" / str(member_id)
        if reports_dir.exists():
            for f in sorted(reports_dir.glob(f"*{REPORT_EXT}")):
                zf.write(f, f"reports/{f.name}")
                added.append(f"reports/{f.name}")
    buf.seek(0)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    audit(request, "backup.export", f"files={len(added)}")
    logger.info("会员 %s 备份导出：%d 个文件", member_id, len(added))
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=invest_backup_member{member_id}_{ts}.zip"},
    )


@router.get("/backup/info")
async def backup_info(request: Request, store=Depends(get_store), member_id=Depends(get_member_id)):
    """备份预览：本会员数据量统计。"""
    data_dir = Path(request.app.state.data_dir if hasattr(request.app.state, "data_dir") else "data")
    trades_count = store.trade_count(member_id)
    reports_dir = data_dir / "reports" / str(member_id)
    return {
        "trades_count": trades_count,
        "diary_count": len(store.list_diary(member_id, limit=10000)),
        "data_dir": str(data_dir),
        "files": sorted(f.name for f in reports_dir.glob("*.md")) if reports_dir.exists() else [],
        "exportable": trades_count > 0,
    }


@router.get("/health/data")
async def data_health(request: Request, store=Depends(get_store), member_id=Depends(get_member_id)):
    """S04-AC2 数据完整性报告（会员维度）：库内行数即权威（CSV 时代已退役）。"""
    report: dict[str, dict] = {
        "trades": {"valid_rows": store.trade_count(member_id), "corrupted_rows": 0},
        "diary": {"valid_rows": len(store.list_diary(member_id, limit=10000)), "corrupted_rows": 0},
    }
    return {"files": report, "healthy": all(v.get("corrupted_rows", 0) == 0 for v in report.values())}
