# Seekr search server. Build the index on a machine with a GPU, `python -m seekr export data/serve.db`, then run
# this image anywhere with data/serve.db (+ its .vectors.npy/.ids.npy snapshot) mounted at /app/data.
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/app/models \
    HF_HUB_OFFLINE=1 \
    SEEKR_HOST=0.0.0.0 \
    SEEKR_DB=/app/data/serve.db \
    SEEKR_TRUSTED_PROXIES=*

# CPU-only PyTorch: ~200 MB instead of GBs of GPU libraries a typical server can't use
COPY requirements.txt .
RUN pip install --no-cache-dir torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r requirements.txt

# Bake the two small models into the image, so the server never downloads anything at startup
COPY seekr/__init__.py seekr/config.py seekr/
RUN HF_HUB_OFFLINE=0 python -c "from sentence_transformers import SentenceTransformer, CrossEncoder; \
from seekr import config; SentenceTransformer(config.EMBED_MODEL); CrossEncoder(config.RERANK_MODEL)"

COPY seeds.txt ./
COPY seekr ./seekr
COPY web ./web

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10m --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"
CMD ["python", "-m", "seekr", "serve"]
