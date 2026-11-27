FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 HF_HOME=/app/models SEEKR_HOST=0.0.0.0 SEEKR_DB=/app/data/serve.db SEEKR_KEYS_DB=/app/data/keys.db \
    SEEKR_TRUSTED_PROXIES=127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16

# CPU-only PyTorch first: the default build adds gigabytes of GPU libraries
RUN pip install --no-cache-dir torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu
COPY pyproject.toml .
COPY src ./src
RUN pip install --no-cache-dir .

# Bake both models into the image, so the server never downloads anything
RUN python -c "from sentence_transformers import CrossEncoder, SentenceTransformer; from seekr import config; \
SentenceTransformer(config.EMBED_MODEL); CrossEncoder(config.RERANK_MODEL)"
ENV HF_HUB_OFFLINE=1

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10m \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"
CMD ["seekr", "serve"]
