import os

import numpy as np

from seekr import db
from seekr.index import embed


def test_similar_meanings_get_close_vectors():
    cat, kitten, sql = embed.embed_texts(["a cat sleeping", "a small kitten napping", "SQL database index"])
    assert np.isclose(np.linalg.norm(cat), 1.0, atol=1e-3)
    assert cat @ kitten > cat @ sql


def test_vector_index_finds_nearest_chunk(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    vectors = {1: [1.0, 0.0], 2: [0.0, 1.0], 3: [0.6, 0.8]}
    for chunk_id, vector in vectors.items():
        conn.execute("INSERT INTO embeddings VALUES (?, ?)", (chunk_id, np.array(vector, np.float32).tobytes()))
    index = embed.VectorIndex(conn)
    results = index.search(np.array([0.0, 1.0], np.float32), k=2)
    assert [chunk_id for chunk_id, _ in results] == [2, 3]
    assert abs(results[1][1] - 0.8) < 1e-3


def test_embed_chunks_is_incremental(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    conn.execute("INSERT INTO documents (id, url, title) VALUES (1, 'https://x.com', 'X')")
    conn.execute("INSERT INTO chunks (doc_id, position, text) VALUES (1, 0, 'hello world')")
    assert embed.embed_chunks(conn) == 1
    assert embed.embed_chunks(conn) == 0


def test_empty_index_returns_nothing(tmp_path):
    assert embed.VectorIndex(db.connect(tmp_path / "t.db")).search(np.zeros(384, np.float32)) == []


def test_uses_the_gpu_when_available():
    import torch
    gpus = {"cuda": torch.cuda.is_available(), "xpu": hasattr(torch, "xpu") and torch.xpu.is_available(),
            "mps": torch.backends.mps.is_available()}
    if any(gpus.values()):
        assert gpus[embed.best_device()]


def add_vectors(conn, vectors):
    for chunk_id, vector in vectors.items():
        conn.execute("INSERT INTO embeddings VALUES (?, ?)", (chunk_id, np.array(vector, np.float32).tobytes()))
    conn.commit()


def test_snapshot_reads_only_new_vectors(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    add_vectors(conn, {1: [1.0, 0.0], 2: [0.0, 1.0]})
    ids, matrix = embed.load_vectors(conn)
    assert list(ids) == [1, 2] and matrix.dtype == np.float16
    assert (tmp_path / "t.db.vectors.npy").exists()
    conn.execute("UPDATE embeddings SET vector = ? WHERE chunk_id = 1", (np.array([9.0, 9.0], np.float32).tobytes(),))
    add_vectors(conn, {3: [0.6, 0.8]})
    ids, matrix = embed.load_vectors(conn)
    assert list(ids) == [1, 2, 3]
    assert matrix[0].tolist() == [1.0, 0.0]  # row 1 came from the snapshot, not from SQLite
    assert np.allclose(matrix[2], [0.6, 0.8], atol=1e-3)


def test_stale_snapshot_is_rebuilt(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    add_vectors(conn, {1: [1.0, 0.0], 2: [0.0, 1.0]})
    embed.load_vectors(conn)
    conn.execute("DELETE FROM embeddings")
    add_vectors(conn, {1: [0.0, 1.0]})
    ids, matrix = embed.load_vectors(conn)
    assert list(ids) == [1] and matrix[0].tolist() == [0.0, 1.0]


def test_cpu_threads_leave_room_on_big_hybrid_cpus():
    import torch

    from seekr import config

    assert 1 <= config.CPU_THREADS <= (os.cpu_count() or 1)
    assert torch.get_num_threads() == config.CPU_THREADS
