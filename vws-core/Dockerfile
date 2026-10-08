# GD-09/SEC-20: immutable official image; no owner files enter the image.
# pragma: allowlist nextline secret - public verified OCI index digest
FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e

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
