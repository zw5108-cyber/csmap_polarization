"""Exceptions exposed by the client."""


class CsmapError(Exception):
    """Base exception for remote requests and response processing."""


class ApiError(CsmapError):
    """The service returned an unsuccessful HTTP status."""

    def __init__(self, status_code: int, path: str, message: str) -> None:
        self.status_code = status_code
        self.path = path
        self.message = message
        super().__init__(f"HTTP {status_code} for {path}: {message}")


class AuthenticationError(ApiError):
    """The service returned HTTP 401 or 403."""


class NetworkError(CsmapError):
    """A connection, timeout, or interrupted download failed."""


class ResponseError(CsmapError):
    """The response cannot be used as the requested data format."""
