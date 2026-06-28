# ---- build the wheel ----
FROM python:3.12-slim AS build
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir build && python -m build --wheel

# ---- runtime ----
FROM python:3.12-slim
LABEL org.opencontainers.image.source="https://github.com/Sahilll15/netdoctor"
LABEL org.opencontainers.image.description="A network health-check CLI that walks the DevOps debugging ladder."
LABEL org.opencontainers.image.licenses="MIT"

# ping + traceroute power two of the rungs (need NET_RAW at run time to actually send)
RUN apt-get update \
    && apt-get install -y --no-install-recommends iputils-ping traceroute \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /app/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl

ENTRYPOINT ["netdoctor"]
CMD ["--help"]
