import pytest

from seekr import config


@pytest.fixture(autouse=True)
def private_database(tmp_path, monkeypatch):
    """Every test gets its own empty database, so no test can touch the real one in data/."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "seekr.db")
