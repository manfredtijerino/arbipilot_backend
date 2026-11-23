"""The one error shape: `{"error": {"code": "...", "message": "..."}}`.

Every error the API returns goes through here, so the frontend and Postman
only ever have to read one format.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

CODES = {
    400: "bad_request",
    401: "not_authenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "invalid_input",
    429: "too_many_requests",
    503: "not_ready",
}

MESSAGES = {
    404: "This address does not exist.",
    405: "This address does not accept that method.",
}


def error_body(code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": code, "message": message}}


def error_response(status_code: int, message: str) -> JSONResponse:
    code = CODES.get(status_code, "error")
    return JSONResponse(status_code=status_code, content=error_body(code, message))


async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = MESSAGES.get(exc.status_code) or str(exc.detail)
    response = error_response(exc.status_code, message)
    if exc.headers:
        response.headers.update(exc.headers)
    return response


async def _invalid_input(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Name the fields that are wrong, never echo what was sent (it may be a password).
    fields = sorted(
        {".".join(str(part) for part in error["loc"][1:]) for error in exc.errors()}
        - {""}
    )
    message = "Some input is missing or invalid"
    if fields:
        message += ": " + ", ".join(fields)
    return error_response(422, message + ".")


async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
    # The details go to the log; the caller gets a plain sentence.
    logger.error(
        "unhandled error path=%r type=%s", request.url.path, type(exc).__name__
    )
    return JSONResponse(
        status_code=500,
        content=error_body("internal_error", "Something went wrong on the server."),
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _invalid_input)
    app.add_exception_handler(Exception, _unexpected)
