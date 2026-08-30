import uuid

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

PROBLEM_MEDIA_TYPE = "application/problem+json"
_TYPE_BASE = "https://udesa-x.dev/errors"


class ProblemError(Exception):
    """An error that becomes a Problem Details response.

    The format is the one documented in ARQUITECTURA.md, "Formato de error":
    RFC 9457, which obsoletes RFC 7807 and keeps the same media type.
    """

    def __init__(
        self,
        *,
        status: int,
        code: str,
        title: str,
        detail: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.headers = headers or {}


def problem_response(
    request: Request,
    *,
    status: int,
    code: str,
    title: str,
    detail: str,
    errors: list[dict] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = {
        "type": f"{_TYPE_BASE}/{code}",
        "title": title,
        "status": status,
        "detail": detail,
        # Correlates the response with the logs. Once OpenTelemetry lands in S10
        # this becomes the real trace id instead of a fresh identifier.
        "traceId": uuid.uuid4().hex,
        "instance": request.url.path,
    }
    if errors:
        body["errors"] = errors
    return JSONResponse(body, status_code=status, media_type=PROBLEM_MEDIA_TYPE, headers=headers)


async def problem_error_handler(request: Request, exc: ProblemError) -> JSONResponse:
    return problem_response(
        request,
        status=exc.status,
        code=exc.code,
        title=exc.title,
        detail=exc.detail,
        headers=exc.headers,
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Translate FastAPI validation failures into the same format.

    Covers E1-H1 CA.5: empty or null required fields are rejected before any
    business logic runs, and the client gets one entry per offending field.
    """
    errors = [
        {
            "field": ".".join(str(part) for part in error["loc"] if part != "body"),
            "message": error["msg"],
        }
        for error in exc.errors()
    ]
    return problem_response(
        request,
        status=422,
        code="validation-failed",
        title="La solicitud tiene campos inválidos",
        detail="Revisá los campos indicados y volvé a intentar.",
        errors=errors,
    )
