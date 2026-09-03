FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RESMED_DB_PATH=/data/resmed.sqlite3 \
    RESMED_MCP_TRANSPORT=stdio \
    RESMED_MCP_HOST=127.0.0.1 \
    RESMED_MCP_PORT=8000

RUN groupadd --system bridge && useradd --system --gid bridge --home /app bridge
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . && mkdir /data && chown bridge:bridge /data && chmod 0700 /data
USER bridge
CMD ["resmed-health-bridge"]
