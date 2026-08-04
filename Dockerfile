FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system --gid 10001 thorbot \
    && useradd --system --uid 10001 --gid thorbot --home-dir /app --shell /usr/sbin/nologin thorbot \
    && mkdir -p /data /app/assets/collectibles \
    && chown -R thorbot:thorbot /app /data

COPY --chown=thorbot:thorbot requirements.lock ./requirements.lock
RUN python -m pip install --no-cache-dir -r requirements.lock

COPY --chown=thorbot:thorbot app ./app
COPY --chown=thorbot:thorbot migrations ./migrations
COPY --chown=thorbot:thorbot assets ./assets
COPY --chown=thorbot:thorbot pyproject.toml README.md LICENSE ./

USER thorbot

VOLUME ["/data"]

HEALTHCHECK --interval=60s --timeout=5s --start-period=90s --retries=3 \
  CMD python -c "import pathlib,time,sys; p=pathlib.Path('/tmp/thor-bot-health'); sys.exit(0 if p.exists() and time.time()-p.stat().st_mtime < 180 else 1)"

CMD ["python", "-m", "app.main"]
