from fastapi import Request
from fastapi.responses import JSONResponse
import structlog

logger = structlog.get_logger()


class PharmaGoException(Exception):
    def __init__(self, status_code: int, message: str, ref: str, log_level: str = "warning"):
        self.status_code = status_code
        self.message = message
        self.ref = ref
        self.log_level = log_level


class ForbiddenException(PharmaGoException):
    def __init__(self, message: str, ref: str):
        super().__init__(403, message, ref, "warning")


class ConflictException(PharmaGoException):
    def __init__(self, message: str, ref: str):
        super().__init__(409, message, ref, "warning")


class NotFoundException(PharmaGoException):
    def __init__(self, message: str, ref: str):
        super().__init__(404, message, ref, "warning")


class ValidationException(PharmaGoException):
    def __init__(self, message: str, ref: str):
        super().__init__(422, message, ref, "warning")


import traceback


async def pharmago_exception_handler(request: Request, exc: PharmaGoException):
    method = getattr(logger, exc.log_level, logger.warning)
    method(exc.message, ref=exc.ref, path=request.url.path)
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "message": exc.message, "data": None, "ref": exc.ref},
    )


async def catch_all_exception_handler(request: Request, exc: Exception):
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    logger.error("unhandled_exception", path=request.url.path, error=str(exc), traceback=tb)
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": "Internal server error", "data": None, "ref": "unhandled"},
    )


EXCEPTION_HANDLERS = {
    PharmaGoException: pharmago_exception_handler,
    Exception: catch_all_exception_handler,
}
