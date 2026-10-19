#!/usr/bin/env python3
"""End-to-end check against a live eBiblio deployment.

Reads the credentials from the environment (``EBIBLIO_USERNAME`` /
``EBIBLIO_PASSWORD``), exercises every operation the MCP server exposes and
prints a sanitised report: status codes, ids, titles and file sizes only — never
credentials, session cookies or loan tokens.

Usage:
    EBIBLIO_USERNAME=... EBIBLIO_PASSWORD=... python scripts/e2e_ebiblio.py
    python scripts/e2e_ebiblio.py --resource 5fcfe8a0114a6f0001f59490 --roundtrip
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ebiblio_mcp.client import EbiblioClient, EbiblioError  # noqa: E402
from ebiblio_mcp.config import Settings  # noqa: E402
from ebiblio_mcp.drm import AdeptToolchain  # noqa: E402

DEFAULT_RESOURCE = "5fcfe8a0114a6f0001f59490"  # La barraca (novela)


def step(name: str, detail: str = "") -> None:
    print(f"[ok]   {name}{(' — ' + detail) if detail else ''}")


def fail(name: str, error: Exception) -> None:
    print(f"[FAIL] {name} — {type(error).__name__}: {error}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resource", default=DEFAULT_RESOURCE)
    parser.add_argument("--roundtrip", action="store_true", help="borrow and return a fresh copy")
    parser.add_argument("--skip-export", action="store_true")
    args = parser.parse_args()

    settings = Settings.from_env()
    client = EbiblioClient(settings)
    failures = 0

    try:
        client.login()
        step("login", f"{settings.base_url} as {settings.username_env}")
    except Exception as exc:  # noqa: BLE001
        fail("login", exc)
        return 1

    try:
        counters = client.account()
        step(
            "account",
            f"name={counters.name} loans_left={counters.loans_remaining}/{counters.loans_limit} "
            f"holds_left={counters.holds_remaining}/{counters.holds_limit}",
        )
    except Exception as exc:  # noqa: BLE001
        failures += 1
        fail("account", exc)

    try:
        results = client.search("blasco ibañez", per_page=3)
        step("search", f"{len(results)} results, first={results[0]['title']!r}")
    except Exception as exc:  # noqa: BLE001
        failures += 1
        fail("search", exc)

    try:
        resource = client.get_resource(args.resource)
        step(
            "resource",
            f"{resource.title!r} available={resource.available} formats={resource.formats}",
        )
    except Exception as exc:  # noqa: BLE001
        failures += 1
        fail("resource", exc)

    loan = None
    try:
        loans = client.loans()
        step("loans", f"{len(loans)} active")
        loan = next((item for item in loans if item.resource_id == args.resource), None)
    except Exception as exc:  # noqa: BLE001
        failures += 1
        fail("loans", exc)

    if loan is None:
        try:
            loan = client.borrow(args.resource)
            step("borrow", f"loan={loan.loan_id} expires={loan.expires_at}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            fail("borrow", exc)
    else:
        try:
            again = client.borrow(args.resource)
            step("borrow (idempotent)", f"loan={again.loan_id} (already on loan)")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            fail("borrow", exc)

    if loan is not None:
        try:
            content, ctype = client.fetch_loan_file(loan.links["acs4"])
            step("download .acsm", f"{len(content)} bytes, {ctype}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            fail("download .acsm", exc)

        try:
            content, ctype = client.fetch_loan_file(loan.links["lcp_computer"])
            step("download .lcpl", f"{len(content)} bytes, {ctype}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            fail("download .lcpl", exc)

        if not args.skip_export:
            try:
                out_dir = settings.downloads_dir / "e2e"
                out_dir.mkdir(parents=True, exist_ok=True)
                acsm = out_dir / "loan.acsm"
                acsm.write_bytes(client.fetch_loan_file(loan.links["acs4"])[0])
                toolchain = AdeptToolchain(settings.adept_dir, settings.libgourou_bin_dir)
                epub = toolchain.fulfil_acsm(acsm, out_dir)
                with zipfile.ZipFile(epub) as archive:
                    names = archive.namelist()
                assert not any("encryption.xml" in name for name in names), "DRM still present"
                step("export epub", f"{epub} ({epub.stat().st_size} bytes, {len(names)} entries)")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                fail("export epub", exc)

    if args.roundtrip and loan is not None:
        try:
            client.return_loan(loan.loan_id)
            step("return", f"loan={loan.loan_id}")
        except EbiblioError as exc:
            failures += 1
            fail("return", exc)

    print(f"\n{failures} failures" if failures else "\nall checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
