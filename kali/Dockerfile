# The Kali execution surface with the #196 HTTP history capture plane.
#
# mitmproxy runs in its OWN isolated Python 3.13 environment: the project's
# runtime venv (/opt/venv) stays on the base image's interpreter and never has
# to resolve mitmproxy's dependency tree, and vice versa.
FROM redamon-kali-sandbox:latest

USER root

ARG UV_VERSION=0.9.7
ARG MITMPROXY_VERSION=12.2.3
ARG MITMPROXY_PYTHON=3.13

ENV DEBIAN_FRONTEND=noninteractive
ENV PATH="/opt/localbin:/root/go/bin:/opt/venv/bin:/usr/local/go/bin:${PATH}"
ENV PYTHONPATH=/opt

RUN (command -v uv >/dev/null 2>&1 || /opt/venv/bin/pip install --no-cache-dir "uv==${UV_VERSION}") \
 && uv python install "${MITMPROXY_PYTHON}" \
 && uv venv --python "${MITMPROXY_PYTHON}" /opt/mitmproxy-env \
 && uv pip install --python /opt/mitmproxy-env/bin/python \
      "mitmproxy==${MITMPROXY_VERSION}" "pydantic>=2,<3"

# The runtime MCP process needs httpx[http2] for the deterministic replay path.
RUN /opt/venv/bin/pip install --no-cache-dir "httpx[http2]==0.28.1"

# Source is normally bind-mounted at /opt/kali by compose; copying it here keeps
# the image usable standalone.
COPY kali /opt/kali
RUN chmod +x /opt/kali/entrypoint.sh /opt/kali/postrun.sh

ENV KALI_HTTP_HISTORY_ROOT=/data \
    KALI_HTTP_CAPTURE_ENABLED=true \
    KALI_HTTP_MAX_BODY_BYTES=5242880 \
    KALI_HTTP_NAMESPACE_POOL=8 \
    KALI_HTTP_LEASE_TTL_S=900 \
    KALI_HTTP_PROXY_HOST=127.0.0.1 \
    KALI_HTTP_PROXY_PORT=8080 \
    KALI_HTTP_REGISTRY_PATH=/run/kali-http/registry.sqlite3

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=10s --retries=5 --start-period=40s \
    CMD /opt/venv/bin/python /opt/kali/healthcheck.py || exit 1

ENTRYPOINT ["/opt/kali/entrypoint.sh"]
