"""Error answers from the API, all in one shape.

Every error the API sends looks like this, the same as a failed job's
"error" field, so the frontend can show it to people as it is:

    { "error": { "title": "Guide not found", "message": "There is no guide with …" } }

In plain English: code anywhere in the backend can `raise ApiError(...)`
with a status code, a short title and a sentence for people. The handlers
at the bottom of this file catch it, and also FastAPI's own errors (an
unknown address, a wrong method, a badly formed request), and turn each one
into that JSON shape.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

# Titles and messages for the errors FastAPI raises by itself.
STANDARD_ERRORS: dict[int, tuple[str, str]] = {
    404: ("Not found", "There is nothing at this address."),
    405: ("Method not allowed", "This address doesn’t accept that kind of request."),
    413: ("Request too large", "The request is larger than the API accepts."),
}


class ApiError(Exception):
    """An error with a message meant for people. Raise it from any endpoint."""

    def __init__(self, status_code: int, title: str, message: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.title = title
        self.message = message
        self.headers = headers


def error_response(status_code: int, title: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    """The JSON answer for an error."""
    return JSONResponse({"error": {"title": title, "message": message}}, status_code=status_code, headers=headers)


async def handle_api_error(_request: Request, error: ApiError) -> JSONResponse:
    return error_response(error.status_code, error.title, error.message, error.headers)


async def handle_http_error(_request: Request, error: HTTPException) -> JSONResponse:
    """FastAPI's own errors: unknown address (404), wrong method (405) and so on."""
    title, message = STANDARD_ERRORS.get(error.status_code, ("Request failed", "The request couldn’t be completed."))
    return error_response(error.status_code, title, message, error.headers)


async def handle_validation_error(_request: Request, _error: RequestValidationError) -> JSONResponse:
    """A request whose body or address doesn't match what the endpoint expects."""
    return error_response(
        422, "Invalid request", "The request is missing something or has a value in the wrong format."
    )


def add_error_handlers(app: FastAPI) -> None:
    """Connects the handlers above to the app."""
    app.add_exception_handler(ApiError, handle_api_error)
    app.add_exception_handler(HTTPException, handle_http_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
