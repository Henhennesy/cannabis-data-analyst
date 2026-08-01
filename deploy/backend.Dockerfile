# The API. Build context is the repo root:
#   docker compose build backend
#
# Two stages so the compiler toolchain and pip's build cache never reach the
# final image. Only the installed site-packages cross the boundary.

# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS build

# --prefix puts everything under one directory that can be copied wholesale.
COPY backend/requirements-app.txt /tmp/requirements-app.txt
RUN pip install --no-cache-dir --prefix=/install -r /tmp/requirements-app.txt

# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm

# Unbuffered so uvicorn's logs reach `docker compose logs` as they happen
# rather than when a buffer fills -- the difference between watching a live
# request and finding out about it later.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

COPY --from=build /install /usr/local

WORKDIR /app
# Only the package and its prompt. Not the tests, not the cleaning pipeline,
# not scripts/ -- an image that can reach the network should carry the least
# code that still serves a request.
COPY backend/__init__.py /app/backend/__init__.py
COPY backend/app /app/backend/app

# Runs as a non-root user with no login shell. The uid is fixed so the bind
# mount for saved analyses has a predictable owner on the host.
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin analyst \
    && mkdir -p /data \
    && chown -R analyst:analyst /data
USER analyst

EXPOSE 8000

# /api/health deliberately does NOT touch Postgres, so this probe cannot keep
# waking Neon from scale-to-zero every 30 seconds. It reports configuration,
# which is what "is the process serving?" actually means here.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

# No --reload: the source is baked into the image, and a reloader in
# production is a second process watching files that will never change.
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
