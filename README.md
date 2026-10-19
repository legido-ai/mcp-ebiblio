# mcp-ebiblio

MCP server for **eBiblio Andalucía** (the Spanish public-library e-lending
platform, `https://andalucia.ebiblio.es`). It drives a library account: search
the catalogue, borrow, list and return loans, download the loan files
(`.acsm` / `.lcpl`) and **export a borrowed book as a DRM-free EPUB** — optionally
converted to MOBI/AZW3 for a Kindle.

- Image: `mcp-ebiblio` (Python 3.13 + libgourou + Calibre)
- Transport: **stdio** (no ports)
- Runs as unprivileged user `10001:10001`
- Credentials: environment variables only, never baked into the image

## Tools

| Tool | Purpose |
|---|---|
| `ebiblio_status` | Session check: account name and remaining loans/reservations. |
| `ebiblio_search` | Catalogue search (`query`, `page`, `per_page`). |
| `ebiblio_resource` | One record: metadata, formats, availability, borrow medium. |
| `ebiblio_borrow` | Borrow a title by resource id (optional e-mail notification). |
| `ebiblio_loans` | Active loans: expiry, download links, LCP passphrase hint. |
| `ebiblio_return` | Return a loan early. |
| `ebiblio_download_loan_file` | Save `.acsm` (Adobe) or `.lcpl` (Thorium/LCP). |
| `ebiblio_export` | Export a loan as a DRM-free `epub`, `mobi` or `azw3`, then return the loan automatically (`return_after=false` to keep it). |

Resource ids are the ones in eBiblio URLs, e.g.
`https://andalucia.ebiblio.es/resources/5fcfe8a0114a6f0001f59490`.

## Prerequisites

- A library card for a participating public library, activated for eBiblio
  (user + password).
- Docker (for the container) or Python 3.13 + `make test`.
- An available loan slot on the account (eBiblio Andalucía: 5 simultaneous).

## Quickstart

```bash
# 1. build the image (compiles libgourou, installs Calibre: ~10 min first time)
make docker

# 2. credentials come from the environment (see .env.example)
export EBIBLIO_USERNAME='you@example.com'
export EBIBLIO_PASSWORD='…'
export EBIBLIO_BASE_URL='https://andalucia.ebiblio.es'

# 3. run the stdio server
make run
```

Wire it into an MCP client (OpenCode, Claude, Hermes…):

```jsonc
{
  "mcp": {
    "ebiblio": {
      "type": "local",
      "command": [
        "docker", "run", "--rm", "-i",
        "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "-v", "ebiblio-data:/data",
        "-e", "EBIBLIO_USERNAME", "-e", "EBIBLIO_PASSWORD",
        "mcp-ebiblio:local"
      ],
      "enabled": true,
      "timeout": 300000
    }
  }
}
```

## Architecture

```
MCP client ──stdio──► ebiblio_mcp.server   (FastMCP tools)
                            │
                            ├── ebiblio_mcp.client   requests session + HTML/JSON parsers
                            │        ├── /v1/resources.json        catalogue search (public)
                            │        ├── /ebiblio_auth_sign_in      login (session cookie)
                            │        ├── /resources/<id>            borrow form + medium id
                            │        ├── /media/<id>/loans_confirmation → loans_activation
                            │        ├── /my_profile/activity       loans, links, counters
                            │        └── /loans/<id>/return         early return
                            │
                            └── ebiblio_mcp.drm      libgourou + Calibre
                                     ├── adept_activate --anonymous   device keys in $EBIBLIO_DATA_DIR/adept
                                     ├── acsmdownloader               .acsm → encrypted publication
                                     ├── adept_remove                 → DRM-free EPUB
                                     └── ebook-convert                EPUB → MOBI/AZW3
```

Data written at run time (never committed):

```
$EBIBLIO_DATA_DIR/
├── adept/         anonymous ADEPT device (device.xml, activation.xml, devicesalt)
└── downloads/     .acsm/.lcpl loan files and exported books
```

## Configuration

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `EBIBLIO_USERNAME` | yes | — | Library account e-mail (alias: `ANDALUCIA_EBIBLIO_USERNAME`). |
| `EBIBLIO_PASSWORD` | yes | — | Library account password (alias: `ANDALUCIA_EBIBLIO_PASSWORD`). |
| `EBIBLIO_BASE_URL` | no | `https://andalucia.ebiblio.es` | Any eBiblio deployment. |
| `EBIBLIO_DATA_DIR` | no | `/data` | Downloads and ADEPT device keys. |
| `EBIBLIO_TIMEOUT` | no | `30` | HTTP timeout, seconds. |
| `EBIBLIO_LOG_LEVEL` | no | `INFO` | Log level (stderr). |
| `EBIBLIO_LIBGOUROU_BIN_DIR` | no | `$PATH` | Where the libgourou tools live. |
| `EBIBLIO_EBOOK_CONVERT` | no | `$PATH` | Calibre's `ebook-convert`. |

## Tests

```bash
make test        # 40 hermetic tests: parsers, flows, toolchain, secret audit
make e2e         # real end-to-end run against eBiblio (needs credentials)
```

The end-to-end script prints a sanitised report (ids, titles, sizes) and never
echoes credentials, cookies or loan tokens.

## Security notes

- Credentials are read from the environment at start-up and are never written to
  disk, logs or the image.
- Loan files are written with mode `0600`; the ADEPT device directory is `0700`.
- DRM removal is limited to the user's **own loans** and never touches the
  library's counters, queues or availability logic.
- Do not publish ports for this server: it is stdio-only.

## Usage note

Exports are produced from your own borrowed copies and remain bound to the loan
(eBiblio loan windows, e.g. 21–60 days). Removing DRM from library loans may be
restricted in your jurisdiction; the ACS4 path is the same fulfilment Adobe
Digital Editions performs with an "authorise without an ID" device.

## Repository layout

```
src/ebiblio_mcp/{config,client,drm,server}.py   server, client and DRM toolchain
tests/                                          hermetic tests + redacted fixtures
scripts/e2e_ebiblio.py                          live end-to-end check
docs/specs/001-ebiblio-mcp/{spec,plan}.md       specification and plan
.specify/memory/constitution.md                 project constitution
```
