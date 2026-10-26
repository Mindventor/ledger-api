"""One error shape for every failure:

    {"error": {"code": "INSUFFICIENT_BALANCE", "message": "...", "details": {...}}}
"""
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    status_code = 400
    code = "BAD_REQUEST"

    def __init__(self, message: str, details: Any = None):
        super().__init__(message)
        self.message = message
        self.details = details


class AccountNotFound(ApiError):
    status_code = 404
    code = "ACCOUNT_NOT_FOUND"


class DuplicateTransaction(ApiError):
    status_code = 409
    code = "DUPLICATE_TRANSACTION"


class DuplicateTransfer(ApiError):
    status_code = 409
    code = "DUPLICATE_TRANSFER"


class InsufficientBalance(ApiError):
    status_code = 422
    code = "INSUFFICIENT_BALANCE"


class InvalidTransfer(ApiError):
    status_code = 400
    code = "INVALID_TRANSFER"


def error_body(code: str, message: str, details: Any = None) -> dict:
    body = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return {"error": body}


def _clean_validation_errors(exc: RequestValidationError) -> list[dict]:
    """Turn Pydantic's error list into short {field, message} items."""
    cleaned = []
    for err in exc.errors():
        loc = [str(part) for part in err.get("loc", ()) if part not in ("body", "query", "path")]
        message = err.get("msg", "Invalid value").removeprefix("Value error, ")
        if err.get("type") == "extra_forbidden":
            message = "This field is not allowed"
        cleaned.append({"field": ".".join(loc) or None, "message": message})
    return cleaned


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(_: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status_code, content=error_body(exc.code, exc.message, exc.details))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=400,
            content=error_body("VALIDATION_ERROR", "Request validation failed", _clean_validation_errors(exc)),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_: Request, exc: StarletteHTTPException):
        codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(codes.get(exc.status_code, "HTTP_ERROR"), str(exc.detail)),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, __: Exception):
        return JSONResponse(status_code=500, content=error_body("INTERNAL_ERROR", "Something went wrong"))
