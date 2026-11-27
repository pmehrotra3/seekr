import httpx

from seekr import config, db
from seekr.crawl import dailymotion

VIDEO = {"id": "x9abc", "title": "Shah Rukh Khan interview", "description": "On <b>Jawan</b> &amp; more",
         "tags": ["srk"], "thumbnail_720_url": "https://s1.dmcdn.net/v/x/x720", "created_time": 1795700000,
         "owner.screenname": "Filmfare", "language": "hi"}
SPAM = {**VIDEO, "id": "x9bad", "title": "Her Secret Billionaire Husband | Full Drama"}


def test_verified_videos_become_searchable_documents(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CRAWL_DELAY", 0)
    asked = []

    def api(request):
        asked.append(dict(request.url.params))
        return httpx.Response(200, json={"list": [VIDEO, SPAM], "has_more": False})

    conn = db.connect(tmp_path / "t.db")
    counts = dailymotion.import_videos(conn, ["srk"], pages=3, transport=httpx.MockTransport(api))
    assert all(params["verified"] == "1" for params in asked)
    assert counts["new"] == 1 and counts["spam"] == len(asked) and counts["known"] == len(asked) - 1
    doc = conn.execute("SELECT * FROM documents").fetchone()
    assert doc["url"] == doc["video"] == "https://www.dailymotion.com/video/x9abc"
    assert doc["image"] == VIDEO["thumbnail_720_url"] and doc["published"].startswith("2026-11")
    assert doc["language"] == ""  # Latin-script title: kept for the English models
    text = conn.execute("SELECT text FROM chunks").fetchone()[0]
    assert "On Jawan & more" in text and "by Filmfare." in text and "srk" in text


def test_a_failing_list_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CRAWL_DELAY", 0)
    transport = httpx.MockTransport(lambda request: httpx.Response(500, json={"error": {}}))
    assert dailymotion.import_videos(db.connect(tmp_path / "t.db"), transport=transport)["new"] == 0


def test_a_timeout_skips_only_that_list(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CRAWL_DELAY", 0)
    calls = []

    def api(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, json={"list": [VIDEO], "has_more": False})

    counts = dailymotion.import_videos(db.connect(tmp_path / "t.db"), transport=httpx.MockTransport(api))
    assert counts["new"] == 1 and len(calls) == 2 * len(dailymotion.CHANNELS)
