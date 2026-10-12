"""Exception handling: every error leaves the API as RFC 9457 problem+json.

Clients get a stable error shape and a request_id they can report.
Internal details (exception messages, stack traces) stay in the logs.
"""

from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from agent_platform.core.request_context import REQUEST_ID_HEADER, get_request_id

log = structlog.get_logger(__name__)

PROBLEM_JSON = "application/problem+json"


def _request_id(request: Request) -> str | None:
    # Unhandled exceptions are rendered outside the middleware stack, where the
    # request context may already be reset, so prefer the copy on request.state.
    request_id: str | None = getattr(request.state, "request_id", None)
    return request_id or get_request_id()


def problem_response(
    request: Request,
    status_code: int,
    detail: str | None = None,
    headers: Mapping[str, str] | None = None,
    **extra: Any,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": HTTPStatus(status_code).phrase,
        "status": status_code,
    }
    if detail:
        body["detail"] = detail
    body.update(extra)

    response_headers = dict(headers or {})
    request_id = _request_id(request)
    if request_id:
        body["request_id"] = request_id
        response_headers[REQUEST_ID_HEADER] = request_id

    return JSONResponse(
        body, status_code=status_code, media_type=PROBLEM_JSON, headers=response_headers
    )


async def _http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    detail = exc.detail if isinstance(exc.detail, str) else None
    return problem_response(request, exc.status_code, detail=detail, headers=exc.headers)


async def _validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return problem_response(
        request,
        HTTPStatus.UNPROCESSABLE_ENTITY,
        detail="Request validation failed",
        errors=jsonable_encoder(exc.errors()),
    )


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.error("unhandled_exception", path=request.url.path, exc_info=exc)
    return problem_response(request, HTTPStatus.INTERNAL_SERVER_ERROR)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)
