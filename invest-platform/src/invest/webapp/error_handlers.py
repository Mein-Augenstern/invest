"""
全局异常处理（S03）：任何未预期异常 → 友好 JSON + traceId，不裸 500。

三类 handler：
  1. Exception → 500 {"error": "服务暂时不可用", "detail": "<error_type>"} + X-Error-Type
  2. HTTPException → 原样透传（已有友好消息）
  3. RequestValidationError → 422 {"error": "输入参数不正确", "detail": "<field>"} 

集成方式：在 webapp/__init__.py 的 create_app 中调用 register_error_handlers(app)。
"""
from __future__ import annotations

import logging
import traceback
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


def register_error_handlers(app: FastAPI) -> None:
    """注册全局异常处理器（幂等，重复调用无副作用）。"""

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        """已有明确状态码的异常——透传 detail（保持 FastAPI 原生行为）。"""
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": str(exc.detail)},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """输入校验失败——提取第一个错误字段给出友好提示。"""
        errors = exc.errors()
        if errors:
            field = errors[0].get("loc", [""])[-1]
            msg = errors[0].get("msg", "参数格式不正确")
            return JSONResponse(
                status_code=422,
                content={"error": f"字段 {field} {msg}", "detail": "validation_error"},
            )
        return JSONResponse(
            status_code=422,
            content={"error": "输入参数不正确", "detail": "validation_error"},
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """兜底：任何未预期异常——500 + 友好消息 + 错误类型头（排障用）。"""
        error_type = type(exc).__name__
        trace_id = getattr(request.state, "trace_id", "")
        logger.error(
            "全局异常: path=%s method=%s type=%s trace_id=%s\n%s",
            request.url.path,
            request.method,
            error_type,
            trace_id,
            traceback.format_exc(),
        )
        resp = JSONResponse(
            status_code=500,
            content={
                "error": "服务暂时不可用，请稍后重试",
                "detail": error_type,
            },
        )
        resp.headers["X-Error-Type"] = error_type
        if trace_id:
            resp.headers["X-Trace-Id"] = trace_id
        return resp
