"""Embeddings: turn text into vectors on the GPU, and find the nearest vectors fast."""
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


class VectorIndex:
    """All chunk vectors in one matrix on the GPU. Search = one matrix multiplication."""

    def __init__(self, conn):
        rows = conn.execute("SELECT chunk_id, vector FROM embeddings ORDER BY chunk_id").fetchall()
        self.chunk_ids = [row["chunk_id"] for row in rows]
        matrix = np.array([np.frombuffer(row["vector"], dtype=np.float32) for row in rows], dtype=np.float32)
        self.matrix = torch.from_numpy(matrix).to(best_device())

    def search(self, query_vector, k=100):
        """Return [(chunk_id, cosine similarity)], best first."""
        if not self.chunk_ids:
            return []
        query = torch.from_numpy(query_vector).to(self.matrix.device)
        scores = self.matrix @ query  # vectors have length 1, so dot product = cosine similarity
        top = torch.topk(scores, min(k, len(self.chunk_ids)))
        return [(self.chunk_ids[i], score) for score, i in zip(top.values.tolist(), top.indices.tolist(), strict=False)]
