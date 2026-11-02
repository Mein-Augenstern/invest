"""S04 数据完整性 API 端点——备份导出/导入 + 数据校验报告。"""
from __future__ import annotations

import io
import json
import logging
import zipfile
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)
router = APIRouter()

DATA_EXTENSIONS = [".csv", ".yaml", ".db", ".json", ".md"]


def _safe_path(base: Path, rel: str) -> Path | None:
    """防目录穿越：只允许 data/ 和 config/ 下的已知扩展名文件。"""
    p = (base / rel).resolve()
    if not str(p).startswith(str(base.resolve())):
        return None
    if p.suffix not in DATA_EXTENSIONS:
        return None
    return p


@router.get("/backup/export")
async def backup_export(request: Request):
    """S04-AC5 导出备份：trades.csv + invest.db + portfolio.local.yaml → zip。"""
    data_dir = Path(request.app.state.data_dir if hasattr(request.app.state, "data_dir") else "data")
    config_dir = data_dir.parent / "config"
    buf = io.BytesIO()
    added = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for d, prefix in [(data_dir, "data/"), (config_dir, "config/")]:
            if not d.exists():
                continue
            for f in d.rglob("*"):
                if f.is_file() and f.suffix in DATA_EXTENSIONS:
                    if f.name.endswith(".local.yaml") or f.name in ("trades.csv", "invest.db"):
                        arcname = prefix + f.relative_to(d).as_posix()
                        zf.write(f, arcname)
                        added.append(arcname)
    buf.seek(0)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger.info("备份导出：%d 个文件", len(added))
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=invest_backup_{ts}.zip"},
    )


@router.get("/backup/info")
async def backup_info(request: Request):
    """备份预览：列出可导出文件清单 + 数据量统计。"""
    data_dir = Path(request.app.state.data_dir if hasattr(request.app.state, "data_dir") else "data")
    trades_count = 0
    trades_path = data_dir / "trades.csv"
    if trades_path.exists():
        with open(trades_path) as f:
            trades_count = sum(1 for _ in f) - 1
    return {
        "trades_count": trades_count,
        "data_dir": str(data_dir),
        "files": [f.name for f in data_dir.iterdir() if f.is_file() and f.suffix in DATA_EXTENSIONS],
        "exportable": trades_count > 0,
    }


@router.get("/health/data")
async def data_health(request: Request):
    """S04-AC2 数据完整性报告：各文件行数 + 最后修改 + 损坏行数。"""
    data_dir = Path(request.app.state.data_dir if hasattr(request.app.state, "data_dir") else "data")
    report: dict[str, dict] = {}
    trades_path = data_dir / "trades.csv"
    if trades_path.exists():
        from ..ledger.trades import load_trades
        loaded = load_trades(trades_path)
        with open(trades_path, newline="", encoding="utf-8-sig") as f:
            total_lines = sum(1 for _ in f) - 1
        report["trades.csv"] = {
            "total_rows": total_lines,
            "valid_rows": len(loaded),
            "corrupted_rows": total_lines - len(loaded),
            "last_modified": datetime.fromtimestamp(trades_path.stat().st_mtime).isoformat(),
        }
    invest_db = data_dir / "invest.db"
    if invest_db.exists():
        report["invest.db"] = {
            "size_bytes": invest_db.stat().st_size,
            "last_modified": datetime.fromtimestamp(invest_db.stat().st_mtime).isoformat(),
        }
    return {"files": report, "healthy": all(v.get("corrupted_rows", 0) == 0 for v in report.values())}
