"""Public query, pagination, and export methods."""

from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping
from urllib.parse import quote

from .errors import ResponseError
from .models import Filters, Page, normalize_names, positive_int
from .transport import Transport


class CsmapClient:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float = 120,
        max_retries: int = 2,
        backoff: float = 0.5,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self._transport = Transport(base_url, timeout, max_retries, backoff, headers)

    @staticmethod
    def _filters(filters: Filters | None, overrides: dict[str, Any]) -> Filters:
        if filters is not None and not isinstance(filters, Filters):
            raise TypeError("filters must be a Filters object")
        try:
            return replace(filters or Filters(), **overrides)
        except TypeError as error:
            raise TypeError(f"Unknown filter argument: {error}") from error

    @staticmethod
    def _name(name: str, prefix: str) -> str:
        if not isinstance(name, str):
            raise ValueError("A single name must be a string")
        normalized = normalize_names(name, prefix)
        if normalized is None or "," in normalized:
            raise ValueError("This method requires exactly one name")
        return quote(normalized, safe="")

    def _page(self, path: str, filters: Filters, **extra: Any) -> Page:
        payload = self._transport.get_json(path, {**filters.as_params(), **extra})
        return Page.from_payload(payload, filters)

    def stats(self) -> dict[str, Any]:
        """Return the archive-wide totals as the original JSON object."""
        payload = self.raw("/api/v1/stats")
        if not isinstance(payload, dict):
            raise ResponseError("Expected an object from the stats endpoint")
        return payload

    def raw(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        """GET an API path and return decoded JSON, without interpreting its schema."""
        return self._transport.get_json("/" + path.lstrip("/"), params or {})

    def posts(self, *, filters: Filters | None = None, **overrides: Any) -> Page:
        return self._page("/api/v1/posts", self._filters(filters, overrides))

    def comments(self, *, filters: Filters | None = None, **overrides: Any) -> Page:
        query = self._filters(filters, overrides)
        self._comment_sort(query)
        return self._page("/api/v1/comments", query)

    @staticmethod
    def _comment_sort(filters: Filters) -> None:
        if filters.sort == "comments":
            raise ValueError("Comments can only be sorted by date or score")

    @staticmethod
    def _search_type(type: str) -> None:
        if type not in ("posts", "comments"):
            raise ValueError("type must be posts or comments")

    def search(
        self, keywords: str, *, type: str = "posts", filters: Filters | None = None,
        **overrides: Any,
    ) -> Page:
        self._search_type(type)
        if not isinstance(keywords, str) or not keywords.strip():
            raise ValueError("keywords must be a non-empty string")
        query = self._filters(filters, overrides)
        if type == "comments":
            self._comment_sort(query)
        return self._page("/api/v1/search", query, q=keywords, type=type)

    def user_posts(self, name: str, *, filters: Filters | None = None, **overrides: Any) -> Page:
        path = f"/api/v1/users/{self._name(name, 'u/')}/posts"
        return self._page(path, self._filters(filters, overrides))

    def user_comments(self, name: str, *, filters: Filters | None = None, **overrides: Any) -> Page:
        query = self._filters(filters, overrides)
        self._comment_sort(query)
        return self._page(f"/api/v1/users/{self._name(name, 'u/')}/comments", query)

    def user_communities(self, name: str, *, filters: Filters | None = None, **overrides: Any) -> Page:
        path = f"/api/v1/users/{self._name(name, 'u/')}/communities"
        return self._page(path, self._filters(filters, overrides))

    def user_timeseries(self, name: str, *, filters: Filters | None = None, **overrides: Any) -> Page:
        path = f"/api/v1/users/{self._name(name, 'u/')}/timeseries"
        return self._page(path, self._filters(filters, overrides))

    def subreddit_users(self, name: str, *, filters: Filters | None = None, **overrides: Any) -> Page:
        path = f"/api/v1/subreddits/{self._name(name, 'r/')}/users"
        return self._page(path, self._filters(filters, overrides))

    def subreddit_timeseries(self, name: str, *, filters: Filters | None = None, **overrides: Any) -> Page:
        path = f"/api/v1/subreddits/{self._name(name, 'r/')}/timeseries"
        return self._page(path, self._filters(filters, overrides))

    def subreddits(self, *, limit: int = 25, page: int = 1) -> Page:
        query = Filters(limit=limit, page=page)
        payload = self._transport.get_json("/api/v1/subreddits/top", {"limit": limit, "page": page})
        return Page.from_payload(payload, query)

    def _iterate(
        self, fetch: Callable[[Filters], Page], query: Filters,
        max_pages: int | None, max_items: int | None,
    ) -> Iterator[dict[str, Any]]:
        if max_pages is not None:
            positive_int(max_pages, "max_pages")
        if max_items is not None:
            positive_int(max_items, "max_items")
        pages_read, items_read = 0, 0
        previous = None
        while max_pages is None or pages_read < max_pages:
            result = fetch(query)
            if result.page != query.page:
                raise ResponseError("Server returned a different page than requested")
            if result.items and result.items == previous:
                raise ResponseError("Server repeated the previous page; pagination stopped")
            for item in result.items:
                yield item
                items_read += 1
                if max_items is not None and items_read >= max_items:
                    return
            pages_read += 1
            if not result.has_more:
                return
            if not result.items:
                raise ResponseError("Server reported more pages but returned no records")
            previous = result.items
            # Server links omit the original filters; rebuild each request from the query.
            query = replace(query, page=query.page + 1)

    def iter_posts(
        self, *, filters: Filters | None = None, max_pages: int | None = None,
        max_items: int | None = None, **overrides: Any,
    ) -> Iterator[dict[str, Any]]:
        return self._iterate(
            lambda query: self.posts(filters=query),
            self._filters(filters, overrides), max_pages, max_items,
        )

    def iter_comments(
        self, *, filters: Filters | None = None, max_pages: int | None = None,
        max_items: int | None = None, **overrides: Any,
    ) -> Iterator[dict[str, Any]]:
        return self._iterate(
            lambda query: self.comments(filters=query),
            self._filters(filters, overrides), max_pages, max_items,
        )

    def iter_search(
        self, keywords: str, *, type: str = "posts", filters: Filters | None = None,
        max_pages: int | None = None, max_items: int | None = None, **overrides: Any,
    ) -> Iterator[dict[str, Any]]:
        return self._iterate(
            lambda query: self.search(keywords, type=type, filters=query),
            self._filters(filters, overrides), max_pages, max_items,
        )

    def export(
        self, resource: str, destination: str | Path, *, name: str | None = None,
        keywords: str | None = None, type: str = "posts", format: str | None = None,
        overwrite: bool = False, filters: Filters | None = None, **overrides: Any,
    ) -> Path:
        """Stream every matching record from a server-supported export endpoint."""
        query = self._filters(filters, overrides)
        if format is None:
            formats = {".csv": "csv", ".ndjson": "ndjson", ".jsonl": "ndjson"}
            format = formats.get(Path(destination).suffix.lower())
        if format not in ("csv", "ndjson"):
            raise ValueError("Use format='csv'/'ndjson', or a .csv/.ndjson/.jsonl filename")
        if not isinstance(overwrite, bool):
            raise ValueError("overwrite must be a boolean")
        if resource in ("posts", "comments", "search"):
            path = f"/api/v1/{resource}"
            if name is not None:
                raise ValueError("Use author/subreddit filters instead of name for this resource")
        elif resource in ("user_posts", "user_comments"):
            path = f"/api/v1/users/{self._name(name, 'u/')}/{resource.removeprefix('user_')}"
        elif resource == "subreddit_users":
            path = f"/api/v1/subreddits/{self._name(name, 'r/')}/users"
        else:
            raise ValueError("Unsupported export resource; use posts, comments, search, user_posts, user_comments, or subreddit_users")
        params = query.as_params()
        params.pop("limit")
        params.pop("page")
        params["format"] = format
        if resource in ("comments", "user_comments"):
            self._comment_sort(query)
        if resource == "search":
            self._search_type(type)
            if not isinstance(keywords, str) or not keywords.strip():
                raise ValueError("Search export requires non-empty keywords")
            if type == "comments":
                self._comment_sort(query)
            params.update(q=keywords, type=type)
        elif keywords is not None:
            raise ValueError("keywords is only supported for search exports")
        return self._transport.download(path, params, destination, format, overwrite)

    def export_posts(self, destination: str | Path, **options: Any) -> Path:
        return self.export("posts", destination, **options)

    def export_comments(self, destination: str | Path, **options: Any) -> Path:
        return self.export("comments", destination, **options)

    def export_search(self, keywords: str, destination: str | Path, **options: Any) -> Path:
        return self.export("search", destination, keywords=keywords, **options)
