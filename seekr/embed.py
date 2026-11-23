"""Embeddings: turn text into vectors on the GPU, and find the nearest vectors fast."""
import os
from pathlib import Path

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

from seekr import config

# BGE models are trained to expect this prefix on short search queries (not on passages).
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
_model = None


def best_device():
    if config.DEVICE:
        return config.DEVICE
    if torch.cuda.is_available():
        return "cuda"  # NVIDIA GPU
    if hasattr(torch, "xpu") and torch.xpu.is_available():
        return "xpu"  # Intel Arc GPU (needs the +xpu build of PyTorch)
    if torch.backends.mps.is_available():
        return "mps"  # Apple Silicon GPU (Metal)
    return "cpu"


def get_model():
    """Load the model once, on the best device. Half precision is ~2x faster on a GPU."""
    global _model
    if _model is None:
        _model = SentenceTransformer(config.EMBED_MODEL, device=best_device())
        if best_device() != "cpu":
            _model.half()
    return _model


def embed_texts(texts):
    vectors = get_model().encode(texts, batch_size=config.EMBED_BATCH, normalize_embeddings=True)
    return vectors.astype(np.float32)


def embed_query(query):
    return embed_texts([QUERY_PREFIX + query])[0]


def embed_chunks(conn, batch_size=1024):
    """Embed every chunk that has no vector yet. The page title goes in too, for context."""
    sql = """SELECT c.id, d.title, c.text FROM chunks c JOIN documents d ON d.id = c.doc_id
             LEFT JOIN embeddings e ON e.chunk_id = c.id WHERE e.chunk_id IS NULL LIMIT ?"""
    total = 0
    while rows := conn.execute(sql, (batch_size,)).fetchall():
        vectors = embed_texts([f"{row['title']}\n{row['text']}" for row in rows])
        conn.executemany(
            "INSERT INTO embeddings VALUES (?, ?)",
            [(row["id"], vector.tobytes()) for row, vector in zip(rows, vectors, strict=False)],
        )
        conn.commit()
        total += len(rows)
        print(f"  embedded {total} chunks on {best_device()}...", flush=True)
    return total


def snapshot_paths(conn):
    """Vector snapshot files next to the database file (None for an in-memory database)."""
    path = conn.execute("PRAGMA database_list").fetchone()[2]
    return (Path(path + ".vectors.npy"), Path(path + ".ids.npy")) if path else (None, None)


def load_vectors(conn, batch=100_000):
    """(chunk ids, float16 matrix) for every embedding.

    Reading 2M vectors out of SQLite takes minutes, so a snapshot is kept next to the database and only the
    rows added since (chunk ids only grow) are read from SQLite.
    """
    vec_path, id_path = snapshot_paths(conn)
    ids, matrix = np.zeros(0, np.int64), np.zeros((0, 0), np.float16)
    if vec_path and vec_path.exists() and id_path.exists():
        ids, matrix = np.load(id_path), np.load(vec_path, mmap_mode="r")
        newest = conn.execute("SELECT IFNULL(MAX(chunk_id), 0) FROM embeddings").fetchone()[0]
        if len(ids) and newest < ids[-1]:  # the database was rebuilt: the snapshot is stale
            ids, matrix = np.zeros(0, np.int64), np.zeros((0, 0), np.float16)
    new_ids, new_parts = [], []
    last = int(ids[-1]) if len(ids) else 0
    sql = "SELECT chunk_id, vector FROM embeddings WHERE chunk_id > ? ORDER BY chunk_id LIMIT ?"
    while rows := conn.execute(sql, (last, batch)).fetchall():
        new_ids.append(np.array([row[0] for row in rows], np.int64))
        new_parts.append(np.array([np.frombuffer(row[1], np.float32) for row in rows]).astype(np.float16))
        last = rows[-1][0]
    if new_parts:
        ids = np.concatenate([ids, *new_ids])
        matrix = np.concatenate([matrix, *new_parts]) if len(matrix) else np.concatenate(new_parts)
        if vec_path:  # write to temporary files, then rename, so a crash never leaves half a snapshot
            for path, array in ((vec_path, matrix), (id_path, ids)):
                with open(path.with_suffix(".tmp"), "wb") as f:
                    np.save(f, array)
                os.replace(path.with_suffix(".tmp"), path)
    return ids, matrix


class VectorIndex:
    """All chunk vectors in one matrix on the GPU. Search = one matrix multiplication."""

    def __init__(self, conn):
        self.chunk_ids, matrix = load_vectors(conn)
        device = best_device()
        dtype = torch.float32 if device == "cpu" else torch.float16  # CPUs are slow at float16 math
        self.matrix = torch.from_numpy(np.ascontiguousarray(matrix)).to(device=device, dtype=dtype)

    def search(self, query_vector, k=100):
        """Return [(chunk_id, cosine similarity)], best first."""
        if not len(self.chunk_ids):
            return []
        query = torch.from_numpy(query_vector).to(device=self.matrix.device, dtype=self.matrix.dtype)
        scores = self.matrix @ query  # vectors have length 1, so dot product = cosine similarity
        top = torch.topk(scores, min(k, len(self.chunk_ids)))
        hits = zip(top.values.tolist(), top.indices.tolist(), strict=True)
        return [(int(self.chunk_ids[i]), score) for score, i in hits]
