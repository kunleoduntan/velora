# Build from a checkout:  docker build -f deploy/Dockerfile -t velora .
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends git postgresql-client && rm -rf /var/lib/apt/lists/*
COPY . /src
RUN pip install "/src[postgres]" && rm -rf /src
RUN useradd -m -u 10001 velora && mkdir /workspace && chown velora /workspace
USER velora
WORKDIR /workspace
ENV VELORA_WORKSPACE=/workspace
EXPOSE 8000
# First run:  docker compose run --rm velora velora init . && ... new-site / install-app (see docs/hosting.md)
CMD ["velora", "start", "--host", "0.0.0.0", "--port", "8000"]
