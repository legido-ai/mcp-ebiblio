"""Tests for the MCP tool layer (stubbed client, no network)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ebiblio_mcp import server as server_module
from ebiblio_mcp.client import EbiblioError, Loan, Resource
from ebiblio_mcp.config import Settings


class StubClient:
    def __init__(self, tmp_path: Path) -> None:
        self.settings = Settings(
            base_url="https://andalucia.ebiblio.es",
            username="user@example.com",
            password="p",
            data_dir=tmp_path,
        )
        self.loan = Loan(
            loan_id="6ad6496b9d08eec7853de5b4",
            resource_id="5fcfe8a0114a6f0001f59490",
            title="La barraca (novela)",
            authors=["Vicente Blasco Ibáñez"],
            expires_at="18 diciembre 2026 a las 17:46",
            links={
                "acs4": "https://andalucia.ebiblio.es/loans/6ad6496b9d08eec7853de5b4?drm=acs4&token=abc",
                "lcp_computer": "https://andalucia.ebiblio.es/loans/6ad6496b9d08eec7853de5b4?drm=lcp&token=def",
            },
            return_url="https://andalucia.ebiblio.es/loans/6ad6496b9d08eec7853de5b4/return",
        )
        self.returned: list[str] = []
        self.borrowed: list[str] = []

    def account(self):
        from ebiblio_mcp.client import AccountCounters

        return AccountCounters(name="Javier", loans_remaining=4, loans_limit=5, holds_remaining=2, holds_limit=2)

    def search(self, query="", page=1, per_page=20, **filters):
        return [{"resource_id": "abc", "title": query or "todo"}]

    def get_resource(self, resource_id: str) -> Resource:
        return Resource(resource_id=resource_id, title="La barraca (novela)", available=True)

    def borrow(self, resource_id: str, notify: bool = False, email: str | None = None) -> Loan:
        self.borrowed.append(resource_id)
        return self.loan

    def loans(self) -> list[Loan]:
        return [] if self.loan.loan_id in self.returned else [self.loan]

    def return_loan(self, loan_id: str) -> None:
        if loan_id != self.loan.loan_id:
            raise EbiblioError("not active")
        self.returned.append(loan_id)

    def fetch_loan_file(self, url: str) -> tuple[bytes, str]:
        if "drm=acs4" in url:
            return b"<fulfillmentToken/>", "application/vnd.adobe.adept+xml"
        return b'{"id":"license"}', "application/vnd.readium.lcp.license.v1.0+json"


@pytest.fixture()
def stub(monkeypatch, tmp_path: Path) -> StubClient:
    client = StubClient(tmp_path)
    monkeypatch.setattr(server_module, "_client", client)
    monkeypatch.setattr(server_module, "_settings", client.settings)
    return client


def test_tool_names_are_registered() -> None:
    tools = asyncio.run(server_module.mcp.list_tools())
    names = {tool.name for tool in tools}
    assert {
        "ebiblio_status",
        "ebiblio_search",
        "ebiblio_resource",
        "ebiblio_borrow",
        "ebiblio_loans",
        "ebiblio_return",
        "ebiblio_download_loan_file",
        "ebiblio_export",
    } <= names


def test_status_and_search(stub: StubClient) -> None:
    status = server_module.ebiblio_status()
    assert status["account"]["loans_limit"] == 5
    assert status["account"]["loans_remaining"] == 4
    results = server_module.ebiblio_search("blasco")
    assert results["results"][0]["title"] == "blasco"


def test_loans_and_borrow_and_return(stub: StubClient) -> None:
    loans = server_module.ebiblio_loans()
    assert loans["count"] == 1
    borrowed = server_module.ebiblio_borrow("5fcfe8a0114a6f0001f59490")
    assert borrowed["loan_id"] == stub.loan.loan_id
    assert server_module.ebiblio_return(stub.loan.loan_id)["returned"] is True
    assert server_module.ebiblio_loans()["count"] == 0


def test_download_loan_file_writes_secret_mode(stub: StubClient) -> None:
    result = server_module.ebiblio_download_loan_file(stub.loan.loan_id, "acsm")
    path = Path(result["path"])
    assert path.suffix == ".acsm"
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.read_bytes() == b"<fulfillmentToken/>"

    lcpl = server_module.ebiblio_download_loan_file(stub.loan.loan_id, "lcpl")
    assert Path(lcpl["path"]).suffix == ".lcpl"


def test_download_rejects_unknown_kind(stub: StubClient) -> None:
    with pytest.raises(ValueError):
        server_module.ebiblio_download_loan_file(stub.loan.loan_id, "pdf")


def test_export_runs_toolchain(stub: StubClient, monkeypatch) -> None:
    from ebiblio_mcp import server as mod

    calls: dict[str, object] = {}

    class FakeToolchain:
        def __init__(self, adept_dir, bin_dir=None):
            calls["adept_dir"] = adept_dir

        def fulfil_acsm(self, acsm_path, work_dir):
            calls["acsm"] = acsm_path
            out = Path(work_dir) / "book.drm-free.epub"
            out.write_bytes(b"epub")
            return out

    monkeypatch.setattr(mod, "AdeptToolchain", FakeToolchain)
    result = mod.ebiblio_export(stub.loan.loan_id)
    assert result["format"] == "epub"
    assert Path(result["path"]).read_bytes() == b"epub"
    assert Path(result["acsm"]).read_bytes() == b"<fulfillmentToken/>"


def test_export_unknown_loan(stub: StubClient) -> None:
    with pytest.raises(EbiblioError):
        server_module.ebiblio_export("deadbeefdeadbeefdeadbeef")
