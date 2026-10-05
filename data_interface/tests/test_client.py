"""Offline contracts for API shapes, pagination, errors, and streaming exports."""

from datetime import date
from email.message import Message
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from csmap_client import (
    ApiError, AuthenticationError, CsmapClient, Filters, NetworkError, Page, ResponseError,
)


class Response(io.BytesIO):
    def __init__(self, body: bytes, content_type: str = "application/json", *, fail_read: bool = False):
        super().__init__(body)
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.fail_read = fail_read
        self.read_sizes = []

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if self.fail_read:
            raise TimeoutError("stream interrupted")
        return super().read(size)


def json_response(payload):
    return Response(json.dumps(payload).encode("utf-8"))


def list_payload(page=1, *, total=12, rows=None):
    if rows is None:
        rows = [{"id": str(index), "subreddit": "science"} for index in range((page - 1) * 10, min(page * 10, total))]
    return {
        "data": rows,
        "meta": {"page": page, "limit": 10, "total": total, "total_pages": (total + 9) // 10},
        "links": {"next": "/api/v1/posts?page=2&limit=10" if page == 1 else None},
    }


def http_error(status, *, retry_after=None):
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return HTTPError("https://example.test/api/v1/posts", status, "error", headers, io.BytesIO(b'{"error":"service error"}'))


class ClientTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict("os.environ", {"CSMAP_API_KEY": "offline-test-key"})
        environment.start()
        self.addCleanup(environment.stop)
        self.client = CsmapClient("https://example.test", max_retries=0, backoff=0)

    @patch("csmap_client.transport.urlopen")
    def test_all_query_routes_match_official_cli(self, request):
        calls = [
            (lambda: self.client.posts(), "/api/v1/posts"),
            (lambda: self.client.comments(), "/api/v1/comments"),
            (lambda: self.client.search("climate"), "/api/v1/search"),
            (lambda: self.client.user_posts("u/mvea"), "/api/v1/users/mvea/posts"),
            (lambda: self.client.user_comments("mvea"), "/api/v1/users/mvea/comments"),
            (lambda: self.client.user_communities("mvea"), "/api/v1/users/mvea/communities"),
            (lambda: self.client.user_timeseries("mvea"), "/api/v1/users/mvea/timeseries"),
            (lambda: self.client.subreddit_users("r/science"), "/api/v1/subreddits/science/users"),
            (lambda: self.client.subreddit_timeseries("science"), "/api/v1/subreddits/science/timeseries"),
            (lambda: self.client.subreddits(), "/api/v1/subreddits/top"),
        ]
        for invoke, path in calls:
            with self.subTest(path=path):
                request.return_value = json_response({"data": []})
                self.assertEqual(invoke().items, [])
                self.assertEqual(urlsplit(request.call_args.args[0].full_url).path, path)

    @patch("csmap_client.transport.urlopen")
    def test_filters_keep_zero_and_encode_names_and_keyword(self, request):
        request.return_value = json_response({"results": [], "has_more": False})
        scope = Filters(subreddit=["r/science", "politics", "science"], author="u/mvea", after=date(2024, 1, 1))
        self.client.search("climate change, 气候", filters=scope, min_score=0, page=2, limit=100)
        params = parse_qs(urlsplit(request.call_args.args[0].full_url).query)
        self.assertEqual(params["subreddit"], ["science,politics"])
        self.assertEqual(params["author"], ["mvea"])
        self.assertEqual(params["q"], ["climate change, 气候"])
        self.assertEqual(params["min_score"], ["0"])
        self.assertEqual(params["after"], ["2024-01-01"])
        self.assertEqual(params["limit"], ["100"])
        self.assertEqual(scope.page, 1)
        self.assertNotIn("before", params)

    def test_page_shapes_preserve_metadata_and_raw(self):
        payload = list_payload()
        page = Page.from_payload(payload, Filters(limit=10))
        self.assertEqual((page.total, page.total_pages, page.has_more), (12, 2, True))
        self.assertIs(page.raw, payload)
        search = Page.from_payload({"results": [{"id": "a"}], "has_more": True, "page": 1, "limit": 10}, Filters())
        self.assertIsNone(search.total)
        self.assertTrue(search.has_more)
        series = Page.from_payload({"data": [{"period": "2024-01"}] * 25, "meta": {"frequency": "month"}}, Filters())
        self.assertFalse(series.has_more)

    def test_search_totals_support_root_and_nested_metadata(self):
        for payload in (
            {"results": [{"id": "a"}], "page": 1, "limit": 10, "total": 322, "total_pages": 33},
            {"results": [{"id": "a"}], "meta": {"page": 1, "limit": 10, "total": 322, "total_pages": 33}},
        ):
            with self.subTest(payload=payload):
                page = Page.from_payload(payload, Filters(limit=10))
                self.assertEqual((page.total, page.total_pages, page.has_more), (322, 33, True))
                self.assertIs(page.raw, payload)

    @patch("csmap_client.transport.urlopen")
    def test_boolean_search_and_date_boundaries_are_forwarded_unchanged(self, request):
        for keywords in ("climate AND policy", "vaccine NOT covid", "brexit OR referendum"):
            with self.subTest(keywords=keywords):
                request.return_value = json_response({"results": [], "has_more": False})
                self.client.search(keywords, after="2024-01-01", before="2024-01-31", min_score=0)
                params = parse_qs(urlsplit(request.call_args.args[0].full_url).query)
                self.assertEqual(params["q"], [keywords])
                self.assertEqual(params["after"], ["2024-01-01"])
                self.assertEqual(params["before"], ["2024-01-31"])
                self.assertEqual(params["min_score"], ["0"])

    @patch("csmap_client.transport.urlopen")
    def test_explicit_search_end_takes_precedence_over_total(self, request):
        request.return_value = json_response({
            "results": [{"id": "a"}], "page": 1, "limit": 10,
            "total": 20000, "total_pages": 2000, "has_more": False,
        })
        self.assertEqual([row["id"] for row in self.client.iter_search("climate")], ["a"])
        self.assertEqual(request.call_count, 1)

    def test_invalid_response_is_not_silently_empty(self):
        for payload in ({"error": "not records"}, {"data": [1]}, {"data": [], "has_more": "false"}, {"data": [], "meta": {"total": -1}}):
            with self.subTest(payload=payload), self.assertRaises(ResponseError):
                Page.from_payload(payload, Filters())

    @patch("csmap_client.transport.urlopen")
    def test_pagination_preserves_filters_despite_incomplete_links(self, request):
        request.side_effect = [json_response(list_payload(1)), json_response(list_payload(2))]
        rows = list(self.client.iter_posts(subreddit="science", after="2024-01-15", min_score=0, limit=10))
        self.assertEqual(len(rows), 12)
        for index, call in enumerate(request.call_args_list, 1):
            params = parse_qs(urlsplit(call.args[0].full_url).query)
            self.assertEqual(params["subreddit"], ["science"])
            self.assertEqual(params["after"], ["2024-01-15"])
            self.assertEqual(params["page"], [str(index)])

    @patch("csmap_client.transport.urlopen")
    def test_search_pagination_uses_has_more_without_total(self, request):
        request.side_effect = [
            json_response({"results": [{"id": "a"}], "page": 1, "has_more": True}),
            json_response({"results": [{"id": "b"}], "page": 2, "has_more": False}),
        ]
        self.assertEqual([row["id"] for row in self.client.iter_search("climate", type="comments")], ["a", "b"])
        for call in request.call_args_list:
            params = parse_qs(urlsplit(call.args[0].full_url).query)
            self.assertEqual(params["q"], ["climate"])
            self.assertEqual(params["type"], ["comments"])

    @patch("csmap_client.transport.urlopen")
    def test_iteration_limits_do_not_fetch_extra_pages(self, request):
        request.return_value = json_response(list_payload())
        self.assertEqual(len(list(self.client.iter_posts(max_items=3))), 3)
        self.assertEqual(request.call_count, 1)
        request.reset_mock()
        request.return_value = json_response(list_payload())
        self.assertEqual(len(list(self.client.iter_posts(max_pages=1))), 10)
        self.assertEqual(request.call_count, 1)

    @patch("csmap_client.transport.urlopen")
    def test_repeated_page_stops_instead_of_looping(self, request):
        rows = [{"id": "same"}]
        request.side_effect = [json_response(list_payload(1, rows=rows)), json_response(list_payload(2, rows=rows))]
        with self.assertRaisesRegex(ResponseError, "repeated"):
            list(self.client.iter_posts(limit=10))

    @patch("csmap_client.transport.urlopen")
    def test_empty_page_with_more_results_is_an_error(self, request):
        request.return_value = json_response({"results": [], "has_more": True})
        with self.assertRaisesRegex(ResponseError, "no records"):
            list(self.client.iter_search("climate"))

    @patch("csmap_client.transport.urlopen")
    def test_auth_failure_is_typed_and_never_retried(self, request):
        for status in (401, 403):
            with self.subTest(status=status):
                request.reset_mock()
                request.side_effect = http_error(status)
                with self.assertRaises(AuthenticationError) as caught:
                    CsmapClient("https://example.test").stats()
                self.assertEqual(caught.exception.status_code, status)
                self.assertEqual(request.call_count, 1)

    @patch("csmap_client.transport.time.sleep")
    @patch("csmap_client.transport.urlopen")
    def test_transient_failure_retries_and_honors_numeric_retry_after(self, request, sleep):
        request.side_effect = [http_error(429, retry_after="3"), json_response({"status": "operational"})]
        self.assertEqual(CsmapClient("https://example.test").stats()["status"], "operational")
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(3.0)

    @patch("csmap_client.transport.time.sleep")
    @patch("csmap_client.transport.urlopen")
    def test_retry_after_is_not_capped_at_thirty_seconds(self, request, sleep):
        request.side_effect = [http_error(429, retry_after="90"), json_response({"status": "operational"})]
        CsmapClient("https://example.test").stats()
        sleep.assert_called_once_with(90.0)

    @patch("csmap_client.transport.time.time", return_value=0)
    @patch("csmap_client.transport.time.sleep")
    @patch("csmap_client.transport.urlopen")
    def test_retry_after_supports_http_date(self, request, sleep, clock):
        request.side_effect = [
            http_error(429, retry_after="Thu, 01 Jan 1970 00:02:00 GMT"),
            json_response({"status": "operational"}),
        ]
        CsmapClient("https://example.test").stats()
        sleep.assert_called_once_with(120.0)

    @patch("csmap_client.transport.time.sleep")
    @patch("csmap_client.transport.urlopen")
    def test_invalid_retry_after_uses_bounded_backoff(self, request, sleep):
        for retry_after in ("not a date", "nan", "inf", "-5"):
            with self.subTest(retry_after=retry_after):
                sleep.reset_mock()
                request.side_effect = [http_error(429, retry_after=retry_after), json_response({"status": "operational"})]
                CsmapClient("https://example.test", backoff=100).stats()
                sleep.assert_called_once_with(30.0)

    @patch("csmap_client.transport.time.sleep")
    @patch("csmap_client.transport.urlopen")
    def test_persistent_server_failure_has_bounded_retries(self, request, sleep):
        request.side_effect = [http_error(500), http_error(500), http_error(500)]
        with self.assertRaises(ApiError) as caught:
            CsmapClient("https://example.test").subreddit_timeseries("science")
        self.assertEqual(caught.exception.status_code, 500)
        self.assertEqual(caught.exception.path, "/api/v1/subreddits/science/timeseries")
        self.assertEqual(request.call_count, 3)

    @patch("csmap_client.transport.time.sleep")
    @patch("csmap_client.transport.urlopen")
    def test_connection_errors_have_bounded_retries(self, request, sleep):
        request.side_effect = URLError("connection refused")
        with self.assertRaises(NetworkError):
            CsmapClient("https://example.test").stats()
        self.assertEqual(request.call_count, 3)

    @patch("csmap_client.transport.urlopen")
    def test_invalid_json_is_a_response_error(self, request):
        request.return_value = Response(b"<html>login</html>", "text/html")
        with self.assertRaises(ResponseError):
            self.client.stats()

    @patch("csmap_client.transport.urlopen")
    def test_streaming_export_is_full_result_and_bounded_memory(self, request):
        body = (json.dumps({"id": "a", "selftext": "x" * 1000, "reddit_url": "https://www.reddit.com/comments/a/"}) + "\n").encode() * 100
        response = Response(body, "application/x-ndjson")
        request.return_value = response
        with tempfile.TemporaryDirectory() as directory:
            target = self.client.export_search("climate change", Path(directory) / "nested" / "posts.ndjson", subreddit="science", limit=10, page=2)
            self.assertTrue(target.is_absolute())
            self.assertEqual(target.read_bytes(), body)
            self.assertEqual(list(target.parent.glob("*.part")), [])
        params = parse_qs(urlsplit(request.call_args.args[0].full_url).query)
        self.assertNotIn("limit", params)
        self.assertNotIn("page", params)
        self.assertEqual(params["format"], ["ndjson"])
        self.assertEqual(params["q"], ["climate change"])
        self.assertTrue(all(size == 64 * 1024 for size in response.read_sizes))

    @patch("csmap_client.transport.urlopen")
    def test_existing_file_is_not_overwritten_by_default(self, request):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "posts.csv"
            target.write_bytes(b"original")
            with self.assertRaises(FileExistsError):
                self.client.export_posts(target)
            self.assertEqual(target.read_bytes(), b"original")
        request.assert_not_called()

    @patch("csmap_client.transport.urlopen")
    def test_successful_explicit_overwrite_preserves_csv_bom(self, request):
        body = b"\xef\xbb\xbfid,title,reddit_url\r\na,hello,https://www.reddit.com/comments/a/\r\n"
        request.return_value = Response(body, "text/csv; charset=utf-8")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "posts.csv"
            target.write_bytes(b"original")
            self.client.export_posts(target, overwrite=True)
            self.assertEqual(target.read_bytes(), body)
            self.assertEqual(list(target.parent.glob("*.part")), [])

    @patch("csmap_client.transport.urlopen")
    def test_interrupted_export_preserves_original_and_cleans_temporary_file(self, request):
        request.return_value = Response(b"unused", "application/x-ndjson", fail_read=True)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "posts.ndjson"
            target.write_bytes(b"original")
            with self.assertRaises(NetworkError):
                self.client.export_posts(target, overwrite=True)
            self.assertEqual(target.read_bytes(), b"original")
            self.assertEqual(sorted(path.name for path in target.parent.iterdir()), ["posts.ndjson"])

    @patch("csmap_client.transport.urlopen")
    def test_export_rejects_paginated_json_and_html(self, request):
        for body, content_type in ((b'{"data": []}', "application/json"), (b"<html>login</html>", "text/plain")):
            with self.subTest(content_type=content_type), tempfile.TemporaryDirectory() as directory:
                request.return_value = Response(body, content_type)
                target = Path(directory) / "posts.ndjson"
                with self.assertRaises(ResponseError):
                    self.client.export_posts(target)
                self.assertFalse(target.exists())
                self.assertEqual(list(target.parent.iterdir()), [])

    @patch("csmap_client.transport.urlopen")
    def test_truncated_content_length_is_not_committed(self, request):
        response = Response(b'{"id":"a"}\n', "application/x-ndjson")
        response.headers["Content-Length"] = "1000"
        request.return_value = response
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "posts.ndjson"
            with self.assertRaises(ResponseError):
                self.client.export_posts(target)
            self.assertFalse(target.exists())

    @patch("csmap_client.transport.urlopen")
    def test_user_and_subreddit_exports_use_server_endpoints(self, request):
        with tempfile.TemporaryDirectory() as directory:
            for resource, name, path in (
                ("user_posts", "u/mvea", "/api/v1/users/mvea/posts"),
                ("user_comments", "mvea", "/api/v1/users/mvea/comments"),
                ("subreddit_users", "r/science", "/api/v1/subreddits/science/users"),
            ):
                request.return_value = Response(b"id\na\n", "text/csv")
                self.client.export(resource, Path(directory) / f"{resource}.csv", name=name)
                self.assertEqual(urlsplit(request.call_args.args[0].full_url).path, path)

    @patch("csmap_client.transport.urlopen")
    def test_raw_preserves_json_and_custom_headers(self, request):
        request.return_value = json_response([{"id": "abc123"}])
        client = CsmapClient("https://example.test", headers={"X-Research": "test"})
        self.assertEqual(client.raw("api/v1/example", {"min_score": 0}), [{"id": "abc123"}])
        self.assertEqual(request.call_args.args[0].get_header("X-research"), "test")

    @patch.dict("os.environ", {"CSMAP_URL": "https://custom.example"})
    @patch("csmap_client.transport.urlopen")
    def test_environment_base_url_is_used(self, request):
        request.return_value = json_response({"status": "operational"})
        CsmapClient().stats()
        self.assertTrue(request.call_args.args[0].full_url.startswith("https://custom.example/api/v1/"))

    @patch("csmap_client.transport.urlopen")
    def test_invalid_queries_fail_before_network(self, request):
        invalid_calls = [
            lambda: self.client.posts(limit=1),
            lambda: self.client.posts(page=0),
            lambda: self.client.posts(page=True),
            lambda: self.client.posts(after="20240101"),
            lambda: self.client.posts(after="2024-02-01", before="2024-01-01"),
            lambda: self.client.posts(min_score=True),
            lambda: self.client.comments(sort="comments"),
            lambda: self.client.search("climate", type="both"),
            lambda: self.client.search(" "),
            lambda: self.client.posts(subreddit=[]),
            lambda: self.client.user_posts("mvea,another"),
            lambda: self.client.raw("https://external.test/data"),
            lambda: list(self.client.iter_posts(max_items=0)),
            lambda: self.client.posts(unknown_filter="value"),
        ]
        for invoke in invalid_calls:
            with self.subTest(invoke=invoke), self.assertRaises((ValueError, TypeError)):
                invoke()
        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
