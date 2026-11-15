# Dashboard assets.
FROM node:22-bookworm-slim AS web
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# Official engine image. We only copy the server binary and libgraphblas.
FROM ghcr.io/hydra-db/hydradb:0.4.0 AS hydra

# Ubuntu 24.04 matches the glibc the 0.4.0 binary was built against.
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-venv ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/venv

COPY --from=hydra /usr/local/bin/graph-node /usr/local/bin/graph-node
COPY --from=hydra /usr/lib/x86_64-linux-gnu/libgraphblas.so.7.4.0 /usr/lib/x86_64-linux-gnu/libgraphblas.so.7.4.0
RUN ln -sf libgraphblas.so.7.4.0 /usr/lib/x86_64-linux-gnu/libgraphblas.so.7 \
    && chmod 755 /usr/local/bin/graph-node

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY dreamgraph ./dreamgraph
COPY results ./results
COPY seed.py ./
COPY scripts/container_boot.sh /usr/local/bin/container_boot.sh
COPY --from=web /src/web/dist ./web/dist
RUN chmod 755 /usr/local/bin/container_boot.sh
EXPOSE 10000
CMD ["/usr/local/bin/container_boot.sh"]
