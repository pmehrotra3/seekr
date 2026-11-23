# Seekr in a container. Docker on a Mac can't reach the Apple GPU, so inside Docker everything runs on the CPU.
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    SEEKR_HOST=0.0.0.0 \
    HF_HOME=/app/data/huggingface

COPY requirements.txt .
# CPU-only PyTorch first: ~200 MB instead of ~2.5 GB of NVIDIA libraries the container couldn't use anyway
RUN pip install --no-cache-dir torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r requirements.txt

COPY seeds.txt ./
COPY seekr ./seekr
COPY web ./web
COPY evals ./evals

EXPOSE 8000
CMD ["python", "-m", "seekr", "serve"]
