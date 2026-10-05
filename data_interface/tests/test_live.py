"""Opt-in authenticated integration checks against narrowly scoped queries."""

import csv
import json
import os
from pathlib import Path
import tempfile
import unittest

from csmap_client import CsmapClient, Filters


@unittest.skipUnless(os.environ.get("CSMAP_LIVE_TESTS") == "1", "Set CSMAP_LIVE_TESTS=1 to query the service with your API key")
class LiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = CsmapClient(timeout=30, max_retries=0)
        cls.scope = Filters(subreddit="science", after="2024-01-15", before="2024-01-16", limit=10)

    def test_stats_and_raw(self):
        self.assertGreater(self.client.stats()["total_posts"], 0)
        self.assertIn("status", self.client.raw("/api/v1/stats"))

    def test_post_and_comment_shapes(self):
        posts = self.client.posts(filters=self.scope)
        comments = self.client.comments(filters=self.scope)
        self.assertEqual(len(posts.items), 10)
        self.assertEqual(len(comments.items), 10)
        self.assertGreater(posts.total, 10)
        self.assertIn("post_id", comments.items[0])
        self.assertIsInstance(posts.items[0]["created_utc"], int)

    def test_real_pagination_keeps_scope(self):
        rows = list(self.client.iter_posts(filters=self.scope, max_items=12))
        self.assertEqual(len(rows), 12)
        self.assertTrue(all(row["subreddit"] == "science" for row in rows))
        self.assertTrue(all("2024-01-15" <= row["created_at"][:10] <= "2024-01-16" for row in rows))
        self.assertEqual(len({row["id"] for row in rows}), 12)

    def test_posts_include_the_entire_before_date(self):
        page = self.client.posts(
            subreddit="science", after="2024-01-16", before="2024-01-16",
            sort="date", order="desc", limit=10,
        )
        self.assertTrue(page.items)
        self.assertTrue(all(row["created_at"].startswith("2024-01-16") for row in page.items))

    def test_search_shape(self):
        page = self.client.search("climate", subreddit="science", after="2024-01-01", before="2024-02-01", limit=10)
        self.assertTrue(page.items)
        self.assertIn("results", page.raw)
        if page.total is not None:
            self.assertGreaterEqual(page.total, len(page.items))
        if page.total_pages is not None:
            self.assertGreaterEqual(page.total_pages, page.page)

    def test_boolean_search_operators(self):
        queries = ("vaccine", "vaccine OR csmapnonexistenttoken", "vaccine AND covid", "vaccine NOT covid")
        pages = {
            query: self.client.search(
                query, subreddit="science", after="2024-01-01", before="2024-01-31", limit=200,
            )
            for query in queries
        }
        self.assertTrue(pages["vaccine"].items)
        self.assertTrue(all(not page.has_more for page in pages.values()))
        ids = {query: {row["id"] for row in page.items} for query, page in pages.items()}
        self.assertEqual(ids["vaccine"], ids["vaccine OR csmapnonexistenttoken"])
        self.assertEqual(ids["vaccine"], ids["vaccine AND covid"] | ids["vaccine NOT covid"])
        self.assertTrue(ids["vaccine AND covid"].isdisjoint(ids["vaccine NOT covid"]))

    def test_user_community_and_monthly_aggregates(self):
        options = {"after": "2024-01-01", "before": "2024-01-31", "limit": 10}
        for fetch in (self.client.user_posts, self.client.user_comments, self.client.user_communities, self.client.user_timeseries):
            with self.subTest(method=fetch.__name__):
                self.assertTrue(fetch("mvea", **options).items)
        self.assertTrue(self.client.subreddit_users("science", **options).items)
        self.assertTrue(self.client.subreddit_timeseries("science", **options).items)
        self.assertTrue(self.client.subreddits(limit=10).items)

    def test_full_exports_have_all_matches_and_extra_text_fields(self):
        page = self.client.posts(filters=self.scope)
        with tempfile.TemporaryDirectory() as directory:
            ndjson = self.client.export_posts(Path(directory) / "posts.ndjson", filters=self.scope)
            csv_path = self.client.export_posts(Path(directory) / "posts.csv", filters=self.scope)
            with ndjson.open(encoding="utf-8") as stream:
                records = [json.loads(line) for line in stream]
            with csv_path.open(encoding="utf-8-sig", newline="") as stream:
                csv_records = list(csv.DictReader(stream))
            self.assertEqual(len(records), page.total)
            self.assertEqual(len(csv_records), page.total)
            self.assertGreater(len(records), page.limit)
            self.assertIn("selftext", records[0])
            self.assertIn("domain", records[0])
            self.assertIn("reddit_url", csv_records[0])

    def test_other_native_export_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            for resource, name, keywords in (
                ("comments", None, None),
                ("search", None, "covid"),
                ("user_posts", "mvea", None),
                ("user_comments", "mvea", None),
                ("subreddit_users", "science", None),
            ):
                with self.subTest(resource=resource):
                    path = self.client.export(
                        resource, Path(directory) / f"{resource}.ndjson",
                        filters=self.scope, name=name, keywords=keywords, author="mvea",
                    )
                    with path.open(encoding="utf-8") as stream:
                        for line in stream:
                            self.assertIsInstance(json.loads(line), dict)


if __name__ == "__main__":
    unittest.main()
