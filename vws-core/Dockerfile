# GD-09/SEC-20: immutable official image; no owner files enter the image.
# pragma: allowlist nextline secret - public verified OCI index digest
FROM python:3.14.8-slim-bookworm@sha256:48b13b003dda20b16f9442b8475aa05fe21bf6579a8c881db92ffb4d8fd20f83

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock ./
RUN python -m pip install --no-cache-dir --require-hashes --no-deps -r requirements.lock \
    && groupadd --gid 10001 vws \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin vws \
    && mkdir -p /app/data /app/logs /app/backups \
    && chown -R 10001:10001 /app
COPY backend ./backend
COPY vws ./vws
COPY config ./config
COPY docs/PROGRESS.md ./docs/PROGRESS.md
USER 10001:10001
HEALTHCHECK --interval=60s --timeout=15s --start-period=90s --retries=3 \
    CMD ["python", "-m", "vws", "--healthcheck"]
# Host runtime and OS-lock heartbeat are implemented; native keyring is required.
ENTRYPOINT ["python", "-m", "vws", "start"]
