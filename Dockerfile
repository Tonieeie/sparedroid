FROM python:3.12-slim

WORKDIR /app
COPY server/ /app/server/
COPY examples/ /app/examples/
COPY README.md /app/README.md
RUN pip install --no-cache-dir "/app/server[ai,mcp]"

# The handler module path (examples.xxx or your own file) is resolved from here.
ENV SPAREDROID_HOST=0.0.0.0 \
    SPAREDROID_PORT=8788 \
    SPAREDROID_DATA_DIR=/data \
    PYTHONUNBUFFERED=1
VOLUME ["/data"]
EXPOSE 8788

RUN useradd --system --uid 10001 bot && mkdir -p /data && chown bot /data
USER bot
CMD ["sparedroid", "serve"]
