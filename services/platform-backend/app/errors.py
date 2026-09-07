from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}
        self.headers = headers


def error_body(request: Request, error: ApiError) -> dict[str, Any]:
    return {
        "code": error.code,
        "message": error.message,
        "request_id": getattr(request.state, "request_id", "unknown"),
        "retryable": error.retryable,
        "details": error.details,
    }


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(request, exc),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = [
            {"location": list(error["loc"]), "message": error["msg"], "type": error["type"]}
            for error in exc.errors()
        ]
        api_error = ApiError(
            422,
            "VALIDATION_ERROR",
            "请求参数不符合要求。",
            details={"errors": errors},
        )
        return JSONResponse(status_code=422, content=error_body(request, api_error))

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
        api_error = ApiError(
            exc.status_code,
            f"HTTP_{exc.status_code}",
            str(exc.detail),
            headers=exc.headers,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(request, api_error),
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, _: Exception) -> JSONResponse:
        api_error = ApiError(
            500,
            "INTERNAL_ERROR",
            "服务暂时不可用，请稍后重试。",
            retryable=True,
        )
        return JSONResponse(status_code=500, content=error_body(request, api_error))
