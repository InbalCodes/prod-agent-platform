"""Per-request context: request ID propagation and the access log.

EXERCISE (Phase 0) — implement `get_request_id` and `RequestContextMiddleware`.
The executable spec is tests/unit/test_request_context.py.

Requirements:
1. Every request gets a request ID:
   - If the client sends a valid `X-Request-ID` header, reuse it
     (valid = 1-128 chars of [A-Za-z0-9._-]). Otherwise generate a new one (uuid4 hex).
   - Never trust the header blindly: it ends up in logs (log injection) and
     in responses.
2. The ID is available anywhere during the request via `get_request_id()`,
   without passing it through function arguments. Use `contextvars`
   (the Python equivalent of Node's AsyncLocalStorage).
   Outside a request, `get_request_id()` returns None.
3. Also store it on `request.state.request_id`. Unhandled exceptions are rendered
   by Starlette's ServerErrorMiddleware, which sits *outside* this middleware,
   so the error handler reads it from there (see core/errors.py).
4. The response carries the `X-Request-ID` header.
5. Exactly one access log line per request:
       event="http_request", method, path, status_code, duration_ms
   If the downstream app raises, log status_code=500 and re-raise.
   Measure with time.perf_counter(), not time.time() — why?

Starting point is BaseHTTPMiddleware (simplest). Production libraries usually
write "pure ASGI" middleware instead — try that once the tests pass if you
want to understand what FastAPI sits on.
"""

import re
import time
from contextvars import ContextVar
from uuid import uuid4

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,128}")

_request_id_var: ContextVar[str | None] = ContextVar(
    "request_id",
    default=None,
)

logger = structlog.get_logger(__name__)


def get_request_id() -> str | None:
    return _request_id_var.get()


def resolve_request_id(header_value: str | None) -> str:
    if header_value and REQUEST_ID_PATTERN.fullmatch(header_value):
        return header_value

    return uuid4().hex


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:

        start_time = time.perf_counter()
        status_code = 500

        header_value = request.headers.get(REQUEST_ID_HEADER)
        request_id = resolve_request_id(header_value)

        token = _request_id_var.set(request_id)
        request.state.request_id = request_id

        try:
            response = await call_next(request)
            status_code = response.status_code

            response.headers[REQUEST_ID_HEADER] = request_id
            return response

        finally:
            duration_ms = (time.perf_counter() - start_time) * 1000
            try:
                logger.info(
                    "http_request",
                    method=request.method,
                    path=request.url.path,
                    status_code=status_code,
                    duration_ms=round(duration_ms, 2),
                )
            finally:
                _request_id_var.reset(token)
