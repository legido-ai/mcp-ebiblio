# Changelog

## 0.1.1 — 2026-10-22

**Registered with Hermes** as the `ebiblio-andalucia` MCP server, so the eight
tools are callable directly in a session. `config.yaml` holds `oci-env` plus a
`docker run` on the `mcp-ebiblio` image with this repository's `src/` mounted
read-only; the credentials are resolved from OCI Vault at spawn time and never
written to the file. Verified with a live handshake: `ebiblio_status` reports
`authenticated: true` for the account and `ebiblio_search` answers from the
catalogue.

## 0.1.0 — 2026-10-19

Initial release: MCP server for eBiblio Andalucía.

- `ebiblio_export` converts to EPUB/MOBI/AZW3 and returns the loan automatically
  once the DRM-free file is on disk (`return_after=false` keeps the loan; a
  failed export never returns it).

- `ebiblio_search` / `ebiblio_resource`: catalogue search and record inspection.
- `ebiblio_borrow` / `ebiblio_loans` / `ebiblio_return`: loan lifecycle through
  the platform's own flows.
- `ebiblio_download_loan_file`: `.acsm` (Adobe) and `.lcpl` (Thorium/LCP) files.
- `ebiblio_export`: DRM-free EPUB via libgourou anonymous ADEPT activation, with
  optional MOBI/AZW3 conversion through Calibre.
- Container image (Python 3.13 + libgourou + Calibre), stdio transport,
  unprivileged user, environment-only credentials.
- 40 hermetic tests plus a live end-to-end script.
