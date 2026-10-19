"""MCP server exposing eBiblio Andalucía (public library e-lending) operations.

Tools: search the catalogue, inspect a record, borrow, list and return loans,
download the loan files (``.acsm`` for Adobe readers, ``.lcpl`` for Thorium) and
export a loan to a DRM-free EPUB (optionally converted to MOBI with Calibre).
"""

from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .client import EbiblioClient, EbiblioError, Loan
from .config import ConfigError, Settings
from .drm import AdeptToolchain, DrmError, convert_ebook

log = logging.getLogger("ebiblio.server")

mcp = FastMCP("ebiblio")

_client: EbiblioClient | None = None
_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings


def get_client() -> EbiblioClient:
    global _client
    if _client is None:
        _client = EbiblioClient(get_settings())
    return _client


def _slug(text: str, fallback: str = "loan") -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", text or "").strip("-").lower()
    return (slug or fallback)[:80]


def _loan_out_dir(loan: Loan) -> Path:
    settings = get_settings()
    target = settings.downloads_dir / f"{_slug(loan.title)}-{loan.loan_id[:8]}"
    target.mkdir(parents=True, exist_ok=True)
    return target


@mcp.tool()
def ebiblio_status() -> dict[str, Any]:
    """Check the eBiblio session: account name and remaining loans/reservations."""
    client = get_client()
    counters = client.account()
    return {
        "base_url": get_settings().base_url,
        "authenticated": True,
        "account": counters.to_dict(),
    }


@mcp.tool()
def ebiblio_search(query: str, page: int = 1, per_page: int = 20) -> dict[str, Any]:
    """Search the eBiblio catalogue by title, author, publisher, topic or ISBN."""
    results = get_client().search(query=query, page=page, per_page=per_page)
    return {"query": query, "page": page, "count": len(results), "results": results}


@mcp.tool()
def ebiblio_resource(resource_id: str) -> dict[str, Any]:
    """Show one catalogue record: metadata, formats and whether it can be borrowed.

    `resource_id` is the id at the end of an eBiblio URL, e.g.
    https://andalucia.ebiblio.es/resources/<resource_id>.
    """
    return get_client().get_resource(resource_id).to_dict()


@mcp.tool()
def ebiblio_borrow(resource_id: str, notify: bool = False, email: str | None = None) -> dict[str, Any]:
    """Borrow a title from the library and return the new loan (id and expiry).

    Set `notify` to ask the platform to e-mail the access links (the account
    address is used unless `email` is given).
    """
    loan = get_client().borrow(resource_id, notify=notify, email=email)
    return loan.to_dict()


@mcp.tool()
def ebiblio_loans() -> dict[str, Any]:
    """List active loans with expiry dates, download links and the LCP passphrase hint."""
    loans = get_client().loans()
    return {"count": len(loans), "loans": [loan.to_dict() for loan in loans]}


@mcp.tool()
def ebiblio_return(loan_id: str) -> dict[str, Any]:
    """Return a loan early so the copy goes back to the library."""
    get_client().return_loan(loan_id)
    return {"loan_id": loan_id, "returned": True}


@mcp.tool()
def ebiblio_download_loan_file(loan_id: str, kind: str = "acsm") -> dict[str, Any]:
    """Download a loan file for external readers.

    `kind` is `acsm` (Adobe Digital Editions / e-readers) or `lcpl` (Thorium /
    LCP-compatible e-readers).  The file is stored under the data directory.
    """
    client = get_client()
    kind = kind.lower().lstrip(".")
    if kind not in ("acsm", "lcpl", "lcp"):
        raise ValueError("kind must be 'acsm' or 'lcpl'")
    loans = {loan.loan_id: loan for loan in client.loans()}
    loan = loans.get(loan_id)
    if loan is None:
        raise EbiblioError(f"loan {loan_id} is not active")
    if kind == "acsm":
        url = loan.links.get("acs4")
        suffix = ".acsm"
    else:
        url = loan.links.get("lcp_computer") or loan.links.get("lcp_reader")
        suffix = ".lcpl"
    if not url:
        raise EbiblioError(f"loan {loan_id} has no {kind} link")
    content, content_type = client.fetch_loan_file(url)
    out_dir = _loan_out_dir(loan)
    path = out_dir / f"{_slug(loan.title)}{suffix}"
    path.write_bytes(content)
    os.chmod(path, 0o600)
    return {
        "loan_id": loan_id,
        "kind": kind,
        "path": str(path),
        "bytes": len(content),
        "content_type": content_type,
    }


@mcp.tool()
def ebiblio_export(
    loan_id: str,
    format: str = "epub",
    out_path: str | None = None,
    return_after: bool = True,
) -> dict[str, Any]:
    """Export a loan as a DRM-free file, then give the copy back to the library.

    The ACS4 loan token is fulfilled with libgourou (anonymous device
    activation) and the ADEPT DRM is removed, so the resulting file needs no
    Adobe account, no Thorium and no LCP passphrase: it opens on any device.
    `format` is `epub` (default), `mobi` or `azw3` for e-readers/mobile.

    Once the export has been produced the loan is returned automatically
    (`return_after=False` keeps it on loan instead).  The loan is never returned
    when the export fails, so a failure leaves the loan usable.
    """
    settings = get_settings()
    client = get_client()
    fmt = format.lower().lstrip(".")
    if fmt not in ("epub", "mobi", "azw3", "pdf"):
        raise ValueError("format must be epub, mobi or azw3")
    loans = {loan.loan_id: loan for loan in client.loans()}
    loan = loans.get(loan_id)
    if loan is None:
        raise EbiblioError(f"loan {loan_id} is not active")
    url = loan.links.get("acs4")
    if not url:
        raise EbiblioError(f"loan {loan_id} has no ACS4 (Adobe) link to fulfil")
    content, _ = client.fetch_loan_file(url)
    out_dir = _loan_out_dir(loan)
    acsm_path = out_dir / f"{_slug(loan.title)}.acsm"
    acsm_path.write_bytes(content)
    os.chmod(acsm_path, 0o600)

    toolchain = AdeptToolchain(settings.adept_dir, settings.libgourou_bin_dir)
    drm_free = toolchain.fulfil_acsm(acsm_path, out_dir)

    produced = drm_free
    if fmt != drm_free.suffix.lstrip("."):
        target = Path(out_path) if out_path else out_dir / f"{_slug(loan.title)}.{fmt}"
        produced = convert_ebook(drm_free, fmt, target, settings.ebook_convert)
    elif out_path:
        produced = Path(out_path)
        produced.parent.mkdir(parents=True, exist_ok=True)
        drm_free.replace(produced)

    result: dict[str, Any] = {
        "loan_id": loan_id,
        "title": loan.title,
        "authors": loan.authors,
        "expires_at": loan.expires_at,
        "format": fmt,
        "path": str(produced),
        "bytes": produced.stat().st_size,
        "acsm": str(acsm_path),
        "loan_returned": False,
    }
    if return_after:
        try:
            client.return_loan(loan_id)
            result["loan_returned"] = True
        except EbiblioError as exc:
            # The file is already safe on disk: report the failure, do not fail.
            result["return_error"] = str(exc)
            log.warning("export ok but returning loan %s failed: %s", loan_id, exc)
    return result


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("EBIBLIO_LOG_LEVEL", "INFO").upper(),
        stream=sys.stderr,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        get_settings()
    except ConfigError as exc:
        log.error("configuration error: %s", exc)
        raise SystemExit(2)
    mcp.run()


if __name__ == "__main__":
    main()
