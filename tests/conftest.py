"""Shared test helpers: fixtures loading and a scriptable fake HTTP session."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

import requests

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def fixture_json(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_response(
    status: int = 200,
    text: str = "",
    url: str = "https://andalucia.ebiblio.es/",
    content_type: str = "text/html; charset=utf-8",
    content: bytes | None = None,
) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.url = url
    response.headers["Content-Type"] = content_type
    response._content = content if content is not None else text.encode("utf-8")
    return response


class FakeSession:
    """Minimal ``requests.Session`` stand-in driven by (method, url) rules."""

    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.calls: list[dict[str, Any]] = []
        self.routes: list[tuple[str, str, Callable[[dict[str, Any]], requests.Response]]] = []

    def add(self, method: str, pattern: str, handler: Callable[[dict[str, Any]], requests.Response]) -> None:
        self.routes.append((method.upper(), pattern, handler))

    def add_static(self, method: str, pattern: str, response: requests.Response) -> None:
        self.add(method, pattern, lambda _kw: response)

    # requests.Session API surface used by the client
    def get(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("POST", url, **kwargs)

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        record = {"method": method.upper(), "url": url, "kwargs": kwargs}
        self.calls.append(record)
        for route_method, pattern, handler in self.routes:
            if route_method != method.upper():
                continue
            if re.search(pattern, url):
                return handler(kwargs)
        raise AssertionError(f"unexpected {method} {url}")

    def calls_for(self, pattern: str, method: str | None = None) -> list[dict[str, Any]]:
        return [
            call
            for call in self.calls
            if re.search(pattern, call["url"]) and (method is None or call["method"] == method)
        ]
