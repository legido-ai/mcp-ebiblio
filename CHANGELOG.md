# Changelog

## 0.1.0 — 2026-10-19

Initial release: MCP server for eBiblio Andalucía.

- `ebiblio_search` / `ebiblio_resource`: catalogue search and record inspection.
- `ebiblio_borrow` / `ebiblio_loans` / `ebiblio_return`: loan lifecycle through
  the platform's own flows.
- `ebiblio_download_loan_file`: `.acsm` (Adobe) and `.lcpl` (Thorium/LCP) files.
- `ebiblio_export`: DRM-free EPUB via libgourou anonymous ADEPT activation, with
  optional MOBI/AZW3 conversion through Calibre.
- Container image (Python 3.13 + libgourou + Calibre), stdio transport,
  unprivileged user, environment-only credentials.
- 40 hermetic tests plus a live end-to-end script.
