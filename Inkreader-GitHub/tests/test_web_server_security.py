from __future__ import annotations

import unittest
from email.message import Message
from types import SimpleNamespace
from unittest.mock import patch

from web_server import InkReadHandler


def handler(origin: str = "", path: str = "/api/health") -> InkReadHandler:
    instance = object.__new__(InkReadHandler)
    headers = Message()
    if origin:
        headers["Origin"] = origin
    instance.headers = headers
    instance.path = path
    instance.server = SimpleNamespace(server_port=3217)
    return instance


class WebServerSecurityTests(unittest.TestCase):
    def test_same_origin_and_non_browser_requests_are_allowed(self) -> None:
        self.assertTrue(handler()._origin_allowed())
        self.assertTrue(handler("http://127.0.0.1:3217")._origin_allowed())
        self.assertTrue(handler("http://localhost:3217")._origin_allowed())

    def test_foreign_browser_origin_is_rejected(self) -> None:
        self.assertFalse(handler("https://example.invalid")._origin_allowed())

    def test_explicit_development_origin_is_allowed(self) -> None:
        with patch.dict(
            "os.environ",
            {"INKREAD_DEV_ORIGIN": "http://127.0.0.1:9000"},
            clear=False,
        ):
            self.assertTrue(handler("http://127.0.0.1:9000")._origin_allowed())


if __name__ == "__main__":
    unittest.main()
