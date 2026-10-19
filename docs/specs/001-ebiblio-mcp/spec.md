# Feature Specification: eBiblio MCP server

**Feature branch**: `001-ebiblio-mcp`
**Status**: implemented
**Scope**: first deployment is **eBiblio Andalucía** (`https://andalucia.ebiblio.es`),
built so other eBiblio instances work by changing `EBIBLIO_BASE_URL`.

## Problem

eBiblio is the Spanish public-library e-lending platform (Cantook/De Marque
front-end). Borrowing, checking what is on loan and getting a readable file out
of a loan all happen through a web UI that requires a session and several
multi-step forms. Agents and readers cannot drive it today.

## User stories

1. **Search** — as a library member I want to search the catalogue and inspect a
   record (formats, availability) before borrowing.
2. **Borrow** — I want to borrow a title by its resource id and get the loan id
   and expiry date back.
3. **Manage** — I want to list my active loans and return one early.
4. **Export** — I want my borrowed book as a file I can read on any device:
   a DRM-free EPUB, or MOBI/AZW3 for a Kindle.

## Functional requirements

- FR-1 The server authenticates with the member's eBiblio credentials supplied
  through environment variables, and re-authenticates transparently when the
  session expires.
- FR-2 Catalogue search uses the platform's public JSON API
  (`/v1/resources.json`) and returns resource ids usable in eBiblio URLs.
- FR-3 Borrowing follows the platform's two-step flow
  (`/media/<medium>/loans_confirmation` → `/media/<medium>/loans_activation`),
  with optional e-mail notification.
- FR-4 Active loans are read from `/my_profile/activity`, including expiry date,
  the LCP passphrase hint (secret question/answer) and every download link.
- FR-5 A loan can be returned early via `/loans/<id>/return`.
- FR-6 Loan files can be saved: `.acsm` (Adobe Digital Editions / e-readers) and
  `.lcpl` (Thorium / LCP e-readers).
- FR-7 A loan can be exported to a DRM-free EPUB by fulfilling the ACS4 token
  with libgourou using an anonymous ADEPT device, and optionally converted to
  MOBI/AZW3 with Calibre.
- FR-8 Failures are reported with the platform's own message (unavailable copy,
  loan limit reached, expired token), never with a fabricated success.

## Non-functional requirements

- NFR-1 No credential, session cookie, loan token or ADEPT key is ever logged,
  printed or committed.
- NFR-2 The server runs as an unprivileged user in a container, over stdio; no
  ports are published.
- NFR-3 Every parser and flow has hermetic tests that need no network and no
  credentials (`make test`).
- NFR-4 A real end-to-end script (`scripts/e2e_ebiblio.py`) exercises the live
  service with the operator's own account.

## Out of scope (for this iteration)

- Reservations/queues, reading progress sync, audiobooks, wish lists.
- LCP decryption (the `.lcpl` file is delivered as-is; DRM removal uses the
  ACS4/Adobe path, which needs no Adobe account).

## Acceptance criteria

- `make test` passes with no failures.
- `python scripts/e2e_ebiblio.py` reports *all checks passed* against
  `https://andalucia.ebiblio.es` with the operator's credentials.
- The exported EPUB opens without DRM (`META-INF/encryption.xml` absent) and
  contains the full book, not the preview.
