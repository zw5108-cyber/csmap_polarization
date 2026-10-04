"""Validated query filters and normalized result pages."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Sequence

from .errors import ResponseError

Names = str | Sequence[str] | None


def normalize_names(value: Names, prefix: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        parts = value.split(",")
    elif isinstance(value, Sequence):
        parts = list(value)
    else:
        raise ValueError("Names must be a string or a sequence of strings")
    names = []
    for part in parts:
        if not isinstance(part, str):
            raise ValueError("Every name must be a string")
        name = part.strip()
        if name.startswith(prefix):
            name = name[len(prefix):]
        if not name or "," in name or "/" in name:
            raise ValueError("Use non-empty names, without URLs or embedded commas")
        if name not in names:
            names.append(name)
    if not names:
        raise ValueError("Provide at least one name, or use None")
    return ",".join(names)


def normalize_date(value: str | date | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError("Dates must be YYYY-MM-DD strings or datetime.date objects")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("Dates must be valid YYYY-MM-DD values") from error
    if parsed.isoformat() != value:
        raise ValueError("Dates must use YYYY-MM-DD")
    return value


def positive_int(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True)
class Filters:
    """Shared filters; date boundary semantics are controlled by the service."""

    subreddit: Names = None
    author: Names = None
    after: str | date | None = None
    before: str | date | None = None
    min_score: int | None = None
    sort: str = "date"
    order: str = "desc"
    limit: int = 25
    page: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "subreddit", normalize_names(self.subreddit, "r/"))
        object.__setattr__(self, "author", normalize_names(self.author, "u/"))
        object.__setattr__(self, "after", normalize_date(self.after))
        object.__setattr__(self, "before", normalize_date(self.before))
        if self.after and self.before and self.after > self.before:
            raise ValueError("after must be on or before before")
        if self.min_score is not None and (
            isinstance(self.min_score, bool) or not isinstance(self.min_score, int)
        ):
            raise ValueError("min_score must be an integer")
        if self.sort not in ("date", "score", "comments"):
            raise ValueError("sort must be date, score, or comments")
        if self.order not in ("asc", "desc"):
            raise ValueError("order must be asc or desc")
        positive_int(self.limit, "limit")
        positive_int(self.page, "page")
        if not 10 <= self.limit <= 200:
            raise ValueError("limit must be between 10 and 200")

    def as_params(self) -> dict[str, Any]:
        return {key: value for key, value in vars(self).items() if value is not None}


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ResponseError(f"Invalid {name} in pagination metadata")
    return value


@dataclass
class Page:
    """A normalized page, with the unmodified decoded JSON in raw."""

    items: list[dict[str, Any]]
    page: int
    limit: int
    total: int | None
    total_pages: int | None
    has_more: bool
    raw: Any

    @classmethod
    def from_payload(cls, payload: Any, filters: Filters) -> "Page":
        if isinstance(payload, list):
            rows, meta = payload, {}
        elif isinstance(payload, dict):
            rows = next(
                (payload[key] for key in ("data", "results", "users", "communities", "series", "items")
                 if isinstance(payload.get(key), list)),
                None,
            )
            if rows is None:
                raise ResponseError("Response does not contain a recognized record list")
            meta = payload.get("meta", {})
            if not isinstance(meta, dict):
                raise ResponseError("Response meta must be an object")
        else:
            raise ResponseError("Expected a JSON object or array")
        if any(not isinstance(row, dict) for row in rows):
            raise ResponseError("Each record must be a JSON object")
        root = payload if isinstance(payload, dict) else {}
        page = _integer(meta.get("page", root.get("page", filters.page)), "page", minimum=1)
        limit = _integer(meta.get("limit", root.get("limit", filters.limit)), "limit", minimum=1)
        total = meta.get("total", root.get("total"))
        total_pages = meta.get("total_pages", root.get("total_pages"))
        if total is not None:
            total = _integer(total, "total")
        if total_pages is not None:
            total_pages = _integer(total_pages, "total_pages")
        if "has_more" in root:
            has_more = root["has_more"]
            if not isinstance(has_more, bool):
                raise ResponseError("has_more must be a boolean")
        elif total_pages is not None:
            has_more = page < total_pages
        elif total is not None:
            has_more = page * limit < total
        elif isinstance(root.get("links"), dict) and "next" in root["links"]:
            has_more = root["links"]["next"] is not None
        else:
            # Timeseries responses contain the complete list without page metadata.
            has_more = False
        return cls(rows, page, limit, total, total_pages, has_more, payload)
