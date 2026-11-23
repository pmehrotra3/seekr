import importlib

import pytest

from seekr import config
from seekr.__main__ import main


def test_read_seeds_skips_blanks_and_comments(tmp_path):
    seeds = tmp_path / "seeds.txt"
    seeds.write_text("# my seeds\nhttps://a.com/\n\n  https://b.com/  \n")
    assert config.read_seeds(seeds) == ["https://a.com/", "https://b.com/"]


def test_project_seeds_are_web_urls_without_repeats():
    seeds = config.read_seeds()
    assert all(seed.startswith(("http://", "https://")) and " " not in seed for seed in seeds)
    assert len(seeds) == len(set(seeds))


def test_stats_prints_seed_count(capsys):
    main(["stats"])
    assert f"seeds:    {len(config.read_seeds())}" in capsys.readouterr().out


def test_unknown_command_fails():
    with pytest.raises(SystemExit):
        main(["fly"])


def test_contact_goes_into_the_user_agent(monkeypatch):
    monkeypatch.setenv("SEEKR_CONTACT", "Ada Lovelace; ada@example.com")
    try:
        importlib.reload(config)
        assert config.USER_AGENT == "SeekrBot/0.1 (Ada Lovelace; ada@example.com)"
    finally:
        monkeypatch.delenv("SEEKR_CONTACT")
        importlib.reload(config)
    assert config.USER_AGENT == "SeekrBot/0.1"
