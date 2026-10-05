"""Offline checks for key files, credential precedence, and secret handling."""

from email.message import Message
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from csmap_client import AuthenticationError, CsmapClient


class Response(io.BytesIO):
    def __init__(self, body, content_type="application/json"):
        super().__init__(body)
        self.headers = Message()
        self.headers["Content-Type"] = content_type


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.key_file = self.directory / "api_key.txt"
        environment = patch.dict("os.environ", {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        default_file = patch("csmap_client.auth.DEFAULT_KEY_FILE", self.key_file)
        default_file.start()
        self.addCleanup(default_file.stop)

    @patch("csmap_client.transport.urlopen")
    def test_default_file_does_not_depend_on_working_directory(self, request):
        self.key_file.write_text("file-test-key\n", encoding="utf-8-sig")
        request.return_value = Response(b'{"status":"operational"}')
        with patch("pathlib.Path.cwd", return_value=self.directory / "elsewhere"):
            CsmapClient("https://example.test").stats()
        self.assertEqual(request.call_args.args[0].get_header("Authorization"), "Bearer file-test-key")

    @patch("csmap_client.transport.urlopen")
    def test_explicit_file_overrides_environment_and_default_file(self, request):
        self.key_file.write_text("default-test-key", encoding="utf-8")
        other_file = self.directory / "other-key.txt"
        other_file.write_text("explicit-file-test-key", encoding="utf-8")
        request.return_value = Response(b'{"status":"operational"}')
        with patch.dict("os.environ", {"CSMAP_API_KEY": "environment-test-key"}):
            CsmapClient("https://example.test", api_key_file=other_file).stats()
        self.assertEqual(request.call_args.args[0].get_header("Authorization"), "Bearer explicit-file-test-key")

    @patch("csmap_client.transport.urlopen")
    def test_explicit_key_has_highest_priority(self, request):
        request.return_value = Response(b'{"status":"operational"}')
        with patch.dict("os.environ", {"CSMAP_API_KEY": "environment-test-key"}):
            CsmapClient("https://example.test", api_key=" parameter-test-key ", api_key_file=self.key_file).stats()
        self.assertEqual(request.call_args.args[0].get_header("Authorization"), "Bearer parameter-test-key")

    @patch("csmap_client.transport.urlopen")
    def test_environment_key_overrides_default_file(self, request):
        self.key_file.write_text("default-test-key", encoding="utf-8")
        request.return_value = Response(b'{"status":"operational"}')
        with patch.dict("os.environ", {"CSMAP_API_KEY": "environment-test-key"}):
            CsmapClient("https://example.test").stats()
        self.assertEqual(request.call_args.args[0].get_header("Authorization"), "Bearer environment-test-key")

    @patch("csmap_client.transport.urlopen")
    def test_missing_key_fails_before_network(self, request):
        with self.assertRaisesRegex(ValueError, "API key required"):
            CsmapClient("https://example.test")
        request.assert_not_called()

    @patch("csmap_client.transport.urlopen")
    def test_blank_and_placeholder_files_fail_before_network(self, request):
        for value in ("", " \n", "PASTE_YOUR_CSMAP_API_KEY_HERE"):
            with self.subTest(value=value):
                self.key_file.write_text(value, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "placeholder"):
                    CsmapClient("https://example.test")
        request.assert_not_called()

    @patch("csmap_client.transport.urlopen")
    def test_invalid_key_error_does_not_contain_secret(self, request):
        for value in ("secret-test-key\nanother-key", "secret-test-key\x00", "secret test key"):
            with self.subTest(value=value), self.assertRaises(ValueError) as caught:
                CsmapClient("https://example.test", api_key=value)
            self.assertNotIn(value, str(caught.exception))
        request.assert_not_called()

    @patch("csmap_client.transport.urlopen")
    def test_invalid_utf8_file_does_not_echo_bytes(self, request):
        self.key_file.write_bytes(b"secret-test-key\xff")
        with self.assertRaisesRegex(ValueError, "UTF-8") as caught:
            CsmapClient("https://example.test")
        self.assertNotIn("secret-test-key", str(caught.exception))
        request.assert_not_called()

    @patch("csmap_client.transport.urlopen")
    def test_explicit_missing_file_does_not_fall_back_to_environment(self, request):
        with patch.dict("os.environ", {"CSMAP_API_KEY": "environment-test-key"}):
            with self.assertRaises(FileNotFoundError):
                CsmapClient("https://example.test", api_key_file=self.key_file)
        request.assert_not_called()

    @patch("csmap_client.transport.urlopen")
    def test_existing_authorization_header_is_preserved(self, request):
        request.return_value = Response(b'{"status":"operational"}')
        with patch.dict("os.environ", {"CSMAP_API_KEY": "environment-test-key"}):
            CsmapClient("https://example.test", headers={"authorization": "Bearer header-test-key", "X-Research": "test"}).stats()
        self.assertEqual(request.call_args.args[0].get_header("Authorization"), "Bearer header-test-key")
        self.assertEqual(request.call_args.args[0].get_header("X-research"), "test")

    @patch("csmap_client.transport.urlopen")
    def test_conflicting_credentials_and_duplicate_headers_are_rejected(self, request):
        for options in (
            {"api_key": "parameter-test-key"},
            {"api_key_file": self.key_file},
            {"headers": {"authorization": "Bearer other-test-key"}},
        ):
            headers = {"Authorization": "Bearer header-test-key", **options.pop("headers", {})}
            with self.subTest(options=options), self.assertRaises(ValueError):
                CsmapClient("https://example.test", headers=headers, **options)
        request.assert_not_called()

    @patch("csmap_client.transport.urlopen")
    def test_download_uses_the_same_authentication_as_queries(self, request):
        self.key_file.write_text("file-test-key", encoding="utf-8")
        request.return_value = Response(b"id,reddit_url\na,https://www.reddit.com/comments/a/\n", "text/csv")
        target = CsmapClient("https://example.test").export_posts(self.directory / "posts.csv")
        self.assertTrue(target.exists())
        self.assertEqual(request.call_args.args[0].get_header("Authorization"), "Bearer file-test-key")

    @patch("csmap_client.transport.urlopen")
    def test_server_error_cannot_echo_bearer_key(self, request):
        key = "private-test-key"
        body = f'{{"message":"Invalid API key: Bearer {key}"}}'.encode()
        request.side_effect = HTTPError("https://example.test/api/v1/stats", 401, "error", Message(), io.BytesIO(body))
        with self.assertRaises(AuthenticationError) as caught:
            CsmapClient("https://example.test", api_key=key).stats()
        self.assertNotIn(key, str(caught.exception))
        self.assertIn("[redacted]", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
