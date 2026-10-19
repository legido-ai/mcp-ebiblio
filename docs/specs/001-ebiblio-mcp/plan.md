# Implementation plan: eBiblio MCP server

## Constitution Check

- [x] Every feature has tests in `/tests` (40 hermetic tests, no credentials).
- [x] `make test` runs the full suite and passes.
- [x] No secrets in code, images or committed config: credentials arrive through
      `EBIBLIO_USERNAME` / `EBIBLIO_PASSWORD`; `tests/test_no_committed_secrets.py`
      enforces it.
- [x] `Makefile` (`run`, `test`) and `README.md` (prerequisites, quickstart,
      architecture) exist.
- [x] Constitution principles respected, including account-scoped operation.

## Technical context

| Piece | Choice | Why |
|---|---|---|
| Language | Python 3.13 | Same runtime as the other legido-ai MCP images. |
| MCP framework | `mcp` (FastMCP, stdio) | stdio server, no ports, launched by the client. |
| HTTP | `requests` + `BeautifulSoup` | The platform has no public API for patrons: `/v1/*` needs a per-account API key that ordinary members do not have, so the member session (cookie) is the only path for loans. |
| Catalogue | `/v1/resources.json` | Public, no auth, gives resource ids + media list. |
| DRM removal | libgourou (`adept_activate`, `acsmdownloader`, `adept_remove`) built from source in the image | Independent ADEPT implementation; anonymous device activation means no Adobe account is needed. |
| Conversion | Calibre `ebook-convert` | EPUB → MOBI/AZW3. |
| Container | two stages: libgourou build (Debian trixie toolchain) + `python:3.13-slim` runtime with Calibre | Reproducible, unprivileged user 10001. |

## Flow notes discovered while implementing

1. Login: `GET /ebiblio_auth_sign_in` → `POST` with `login`, `password`,
   `authenticity_token`, `remember_me`.
2. Borrow is a **GET then POST** pair:
   `GET /media/<medium_id>/loans_confirmation?_resource_id=…&notify=…&email=…`
   returns a confirmation page whose form POSTs to
   `/media/<medium_id>/loans_activation`.
3. The `<medium_id>` only exists on the resource page (`/resources/<id>`), not in
   the catalogue API.
4. Loan links (`drm=acs4`, `drm=lcp`, `viewer=web_reader`) are per-page-load and
   carry a nonce/timestamp/token: they are re-read from `/my_profile/activity`
   for every download.
5. The "Descargar EPUB" link on a resource page is a *preview* (a few chapters,
   no DRM) — the full book only exists behind ACS4/LCP.
6. ACS4 fulfilment works with an anonymous ADEPT device: the loan token is
   `auth="user"` but the ACS server accepts an anonymously activated device
   (the same mode Adobe Digital Editions offers as "authorise without an ID").

## Complexity tracking

- **libgourou source**: upstream lives on a forge behind a bot wall, so the image
  clones the maintained GitHub mirror (`rledisez/libgourou`, `rledisez/uPDFParser`).
  Overridable with `--build-arg LIBGOUROU_REPO=…`.
- **LCP not decrypted**: the LCP license passphrase shown by the platform
  (secret question answer) does not validate against the issued license's
  `key_check`, so LCP decryption is deliberately out of scope; the ACS4 path
  produces the same DRM-free EPUB without needing that passphrase.
