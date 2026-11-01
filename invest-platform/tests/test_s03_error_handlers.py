"""S03 全局异常处理测试——任何异常不裸 500，给友好 JSON。"""
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def test_app():
    """最小化 FastAPI app（只注册异常处理器，不挂业务路由）。"""
    from invest.webapp.error_handlers import register_error_handlers
    app = FastAPI()
    register_error_handlers(app)

    # 测试用端点
    @app.get("/test/ok")
    def ok():
        return {"ok": True}

    @app.get("/test/crash")
    def crash():
        raise RuntimeError("unexpected error for testing")

    @app.get("/test/http-error")
    def http_error():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="找不到资源")

    @app.post("/test/validate")
    def validate(data: dict):
        from pydantic import BaseModel, ValidationError
        class Item(BaseModel):
            quantity: float
        try:
            Item(**data)
        except ValidationError as e:
            from fastapi.exceptions import RequestValidationError
            raise RequestValidationError(e.errors())
        return {"ok": True}

    return TestClient(app, raise_server_exceptions=False)


class TestGlobalExceptionHandler:
    def test_normal_request(self, test_app):
        resp = test_app.get("/test/ok")
        assert resp.status_code == 200

    def test_unexpected_exception_returns_500_with_friendly_message(self, test_app):
        resp = test_app.get("/test/crash")
        assert resp.status_code == 500
        data = resp.json()
        assert "error" in data
        assert "暂时不可用" in data["error"]
        assert data["detail"] == "RuntimeError"

    def test_unexpected_exception_has_error_type_header(self, test_app):
        resp = test_app.get("/test/crash")
        assert resp.headers.get("X-Error-Type") == "RuntimeError"

    def test_http_exception_passthrough(self, test_app):
        resp = test_app.get("/test/http-error")
        assert resp.status_code == 404
        assert "找不到" in resp.json()["error"]

    def test_validation_error_returns_422(self, test_app):
        resp = test_app.post("/test/validate", json={"quantity": "not_a_number"})
        assert resp.status_code == 422
        data = resp.json()
        assert "error" in data
        assert data["detail"] == "validation_error"
