"""GET requests and atomic, bounded-memory server exports."""

import http.client
import json
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from .errors import ApiError, AuthenticationError, NetworkError, ResponseError

DEFAULT_URL = "https://csmap-social-archive.apps.cloud.rt.nyu.edu"
RETRY_STATUSES = {429, 500, 502, 503, 504}
NETWORK_EXCEPTIONS = (URLError, TimeoutError, OSError, http.client.HTTPException)


class Transport:
    def __init__(
        self,
        base_url: str | None,
        timeout: float,
        max_retries: int,
        backoff: float,
        headers: Mapping[str, str] | None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("CSMAP_URL") or DEFAULT_URL).rstrip("/")
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("base_url must be an absolute HTTP(S) URL without query or fragment")
        for value, name in ((timeout, "timeout"), (backoff, "backoff")):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} must be a finite number")
        if timeout <= 0 or backoff < 0:
            raise ValueError("timeout must be positive and backoff non-negative")
        if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
            raise ValueError("max_retries must be a non-negative integer")
        self.timeout, self.max_retries, self.backoff = timeout, max_retries, backoff
        self.headers = {"User-Agent": "csmap-python-client/0.1.0", **dict(headers or {})}

    def _delay(self, attempt: int, retry_after: str | None = None) -> None:
        delay = self.backoff * (2 ** min(attempt, 10))
        if retry_after:
            try:
                server_delay = float(retry_after)
                if math.isfinite(server_delay):
                    delay = max(delay, server_delay)
            except ValueError:
                pass
        time.sleep(min(30.0, max(0.0, delay)))

    def open(self, path: str, params: Mapping[str, Any], accept: str):
        if not path.startswith("/api/v1/") or "?" in path or "#" in path:
            raise ValueError("Use an /api/v1/... path and pass query parameters separately")
        query = urlencode({key: value for key, value in params.items() if value is not None})
        url = self.base_url + path + ("?" + query if query else "")
        headers = {"Accept": accept, **self.headers}
        request = Request(url, headers=headers, method="GET")
        for attempt in range(self.max_retries + 1):
            try:
                return urlopen(request, timeout=self.timeout)
            except HTTPError as error:
                with error:
                    detail = error.read(4096).decode("utf-8", "replace")
                    status, retry_after = error.code, error.headers.get("Retry-After")
                if status in RETRY_STATUSES and attempt < self.max_retries:
                    self._delay(attempt, retry_after)
                    continue
                try:
                    payload = json.loads(detail)
                    if isinstance(payload, dict):
                        detail = str(payload.get("message") or payload.get("error") or detail)
                except ValueError:
                    pass
                error_type = AuthenticationError if status in (401, 403) else ApiError
                raise error_type(status, path, detail.strip()[:500]) from None
            except NETWORK_EXCEPTIONS as error:
                if attempt < self.max_retries:
                    self._delay(attempt)
                    continue
                raise NetworkError(f"Could not reach {path}: {error}") from error
        raise AssertionError("Unreachable retry state")

    def get_json(self, path: str, params: Mapping[str, Any]) -> Any:
        try:
            with self.open(path, params, "application/json") as response:
                body = response.read()
        except NETWORK_EXCEPTIONS as error:
            raise NetworkError(f"Reading {path} failed: {error}") from error
        try:
            return json.loads(body.decode("utf-8-sig"))
        except (ValueError, UnicodeError) as error:
            raise ResponseError(f"Expected JSON from {path}; received an invalid response") from error

    def download(
        self,
        path: str,
        params: Mapping[str, Any],
        destination: str | Path,
        format: str,
        overwrite: bool,
    ) -> Path:
        target = Path(destination).expanduser().absolute()
        if target.exists() and not overwrite:
            raise FileExistsError(f"Destination already exists: {target}")
        if target.is_dir():
            raise IsADirectoryError(str(target))
        target.parent.mkdir(parents=True, exist_ok=True)
        expected = {"csv": "text/csv", "ndjson": "application/x-ndjson"}[format]
        temporary = None
        try:
            with self.open(path, params, expected) as response:
                content_type = response.headers.get_content_type()
                allowed = {expected, "text/plain", "application/octet-stream"}
                if format == "ndjson":
                    allowed.add("application/ndjson")
                if content_type not in allowed:
                    raise ResponseError(f"Expected {format} from {path}, received {content_type}")
                with tempfile.NamedTemporaryFile(
                    dir=target.parent, prefix=f".{target.name}.", suffix=".part", delete=False
                ) as output:
                    temporary = Path(output.name)
                    first = True
                    while True:
                        try:
                            chunk = response.read(64 * 1024)
                        except NETWORK_EXCEPTIONS as error:
                            raise NetworkError(f"Export from {path} was interrupted: {error}") from error
                        if not chunk:
                            break
                        if first and chunk.lstrip().lower().startswith((b"<!doctype html", b"<html")):
                            raise ResponseError("Export returned an HTML page instead of data")
                        first = False
                        output.write(chunk)
                    expected_length = response.headers.get("Content-Length")
                    if expected_length is not None and output.tell() != int(expected_length):
                        raise ResponseError("Export ended before the complete response was received")
            if overwrite:
                os.replace(temporary, target)
            else:
                # Same-directory hard links commit atomically without replacing an existing file.
                os.link(temporary, target)
            return target
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
