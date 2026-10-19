# syntax=docker/dockerfile:1
#
# eBiblio MCP server image.
#
# Stage 1 builds libgourou (an independent implementation of Adobe's ADEPT
# protocol) from source; stage 2 is the Python runtime that also carries Calibre
# for MOBI/AZW3 conversion.  No credentials are baked into the image: everything
# arrives through environment variables at run time.

FROM python:3.13-slim AS libgourou

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential git ca-certificates \
        libzip-dev libssl-dev libcurl4-openssl-dev libpugixml-dev \
    && rm -rf /var/lib/apt/lists/*

# Pin the sources so builds stay reproducible; override with --build-arg.
ARG LIBGOUROU_REPO=https://github.com/rledisez/libgourou.git
ARG LIBGOUROU_REF=master
ARG UPDFPARSER_REPO=https://github.com/rledisez/uPDFParser.git
ARG UPDFPARSER_REF=master

WORKDIR /usr/src
RUN git clone --depth 1 --branch "${LIBGOUROU_REF}" "${LIBGOUROU_REPO}" libgourou \
    && git clone --depth 1 --branch "${UPDFPARSER_REF}" "${UPDFPARSER_REPO}" libgourou/lib/updfparser \
    && cd libgourou/lib/updfparser && make BUILD_STATIC=1 BUILD_SHARED=0 \
    && cd /usr/src/libgourou && make -j"$(nproc)" \
    && mkdir -p /out/bin /out/lib \
    && cp utils/acsmdownloader utils/adept_activate utils/adept_remove utils/adept_loan_mgt /out/bin/ \
    && cp libgourou.so.* /out/lib/


FROM python:3.13-slim AS runtime

LABEL org.opencontainers.image.title="mcp-ebiblio" \
      org.opencontainers.image.description="MCP server for eBiblio Andalucía: search, borrow, return and export loans" \
      org.opencontainers.image.source="https://github.com/legido-ai/mcp-ebiblio"

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    EBIBLIO_DATA_DIR=/data

RUN apt-get update && apt-get install -y --no-install-recommends \
        libzip5 libssl3t64 libcurl4t64 libpugixml1v5 \
        calibre ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /data

COPY --from=libgourou /out/bin/ /usr/local/bin/
COPY --from=libgourou /out/lib/ /usr/local/lib/
RUN ldconfig && adept_activate --version >/dev/null && acsmdownloader --version >/dev/null

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
ENV PYTHONPATH=/app/src

# Unprivileged runtime user; /data must be writable for ADEPT keys and exports.
RUN useradd --uid 10001 --create-home --home-dir /home/ebiblio ebiblio \
    && mkdir -p /data && chown -R 10001:10001 /data /app
USER 10001:10001

VOLUME ["/data"]
ENTRYPOINT ["python", "-m", "ebiblio_mcp"]
