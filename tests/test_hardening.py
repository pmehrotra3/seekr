import logging

import pytest

from seekr import config, db, doctor


@pytest.fixture
def empty_project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "data" / "seekr.db")
    monkeypatch.setattr(config, "SEEDS_FILE", tmp_path / "seeds.txt")
    return tmp_path


def test_doctor_explains_how_to_fix_a_missing_database(empty_project):
    ok, message = doctor.check_database()
    assert not ok and "python -m seekr crawl" in message


def test_doctor_spots_an_unfinished_index(empty_project):
    conn = db.connect()
    db.save_page(conn, "https://x.com/", "https://x.com/", 200, "X", "", [])
    conn.commit()
    ok, message = doctor.check_database()
    assert not ok and "documents is empty" in message and "seekr index" in message


def test_doctor_checks_seeds_and_python(empty_project):
    assert doctor.check_seeds()[0] is False
    (empty_project / "seeds.txt").write_text("https://a.com/\n")
    assert doctor.check_seeds() == (True, "1 seed URLs in seeds.txt")
    assert doctor.check_python()[0]


def test_doctor_reports_models_missing_on_a_fresh_machine(monkeypatch):
    import huggingface_hub

    def no_cache_yet():
        raise huggingface_hub.CacheNotFound("no cache", cache_dir="/nowhere")

    monkeypatch.setattr(huggingface_hub, "scan_cache_dir", no_cache_yet)
    ok, message = doctor.check_models()
    assert not ok and "not downloaded yet" in message


def test_run_checks_keeps_going_after_a_crash(monkeypatch, capsys):
    def broken():
        raise RuntimeError("boom")

    monkeypatch.setattr(doctor, "CHECKS", [broken, doctor.check_python])
    assert doctor.run_checks() is False
    output = capsys.readouterr().out
    assert "✗ broken crashed: boom" in output and "✓ Python" in output


def test_crawler_logs_skipped_hosts(tmp_path, caplog):
    import asyncio

    import httpx

    from seekr import crawler

    conn = db.connect(tmp_path / "t.db")
    down = httpx.MockTransport(lambda request: httpx.Response(503))
    with caplog.at_level(logging.WARNING, logger="seekr.crawler"):
        asyncio.run(crawler.crawl(["https://example.com/"], conn, transport=down))
    assert "example.com: robots.txt unreachable" in caplog.text
