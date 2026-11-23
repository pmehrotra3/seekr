"""Measure embedding and reranking speed on each available device.

Usage: python tools/bench_device.py [--chunks 4096]
"""
import argparse
import time

import torch
from sentence_transformers import CrossEncoder, SentenceTransformer

from seekr import config

torch.set_num_threads(config.CPU_THREADS)

# ~300 words, the size of a real chunk
TEXT = ("Search engines split pages into chunks, embed each chunk as a vector and compare it with the query. " * 20)


def sync(device):
    if device == "xpu":
        torch.xpu.synchronize()
    elif device == "cuda":
        torch.cuda.synchronize()


def bench(device, n_chunks):
    model = SentenceTransformer(config.EMBED_MODEL, device=device)
    reranker = CrossEncoder(config.RERANK_MODEL, device=device, max_length=config.RERANK_MAX_TOKENS)
    if device != "cpu":
        model.half()
        reranker.model.half()
    texts = [TEXT] * n_chunks
    model.encode(texts[:128], batch_size=config.EMBED_BATCH)  # warm up (kernel compilation)
    sync(device)
    start = time.perf_counter()
    model.encode(texts, batch_size=config.EMBED_BATCH)
    sync(device)
    embed_rate = n_chunks / (time.perf_counter() - start)

    pairs = [("how do search engines rank pages", TEXT)] * config.RERANK_TOP
    reranker.predict(pairs)
    times = []
    for _ in range(10):
        start = time.perf_counter()
        reranker.predict(pairs)
        sync(device)
        times.append(time.perf_counter() - start)
    return embed_rate, sorted(times)[len(times) // 2] * 1000


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunks", type=int, default=4096)
    args = parser.parse_args()
    devices = ["cpu"]
    if torch.cuda.is_available():
        devices.append("cuda")
    if hasattr(torch, "xpu") and torch.xpu.is_available():
        devices.append("xpu")
    print(f"{'device':8} {'embed chunks/s':>15} {'rerank top-' + str(config.RERANK_TOP) + ' ms':>17}")
    for device in devices:
        rate, ms = bench(device, args.chunks)
        print(f"{device:8} {rate:15.0f} {ms:17.0f}")


if __name__ == "__main__":
    main()
